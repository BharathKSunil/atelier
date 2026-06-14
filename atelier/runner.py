"""Per-project background pipeline runner.

Runs the four phase scripts as sequential subprocesses in a daemon thread.
Exposes lock-guarded live status, tees output to a durable per-run log file
(timestamped, never truncated), supports cancellation and a stall watchdog, and
records every run in the `runs` table so history survives a server restart.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque

from . import config, db
from .logsetup import get_logger

_log_mod = get_logger("atelier.runner")

# phases run as `python -m atelier.pipeline.<name>` subprocesses (isolation: a phase
# crash never kills the server; models reload per run).
PHASES = [
    ("index",   "atelier.pipeline.index", lambda folder, dbp: ["--photos", folder, "--db", dbp]),
    ("cluster", "atelier.pipeline.cluster", lambda folder, dbp: ["--db", dbp]),
    ("series",  "atelier.pipeline.series", lambda folder, dbp: ["--db", dbp]),
    ("score",   "atelier.pipeline.score", lambda folder, dbp: ["--db", dbp]),
]
PHASE_NAMES = [p[0] for p in PHASES]
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_LOG_LINES = 5000   # in-memory ring buffer for the live UI (full log is on disk)
ERROR_TAIL = 40        # lines of a crashed phase's output kept as error_detail


class Runner:
    def __init__(self, db_path, log_path=None, runs_dir=None):
        self.db_path = db_path
        self.log_path = log_path        # back-compat "latest" log mirror
        self.runs_dir = runs_dir        # ~/.atelier/<slug>/runs
        self.lock = threading.Lock()
        self._event = threading.Event()
        self.log = deque(maxlen=MAX_LOG_LINES)   # entries: {"n", "ts", "t"}
        self._seq = 0
        self._fh = None
        self._log_file = None
        self._proc = None
        self._cancelled = False
        self._stalled = False
        self._last_output = 0.0
        self._reconciled = False
        self._phases = PHASES
        self._flags = {}
        self.run_id = None
        self.state = {
            "running": False, "phase": None, "phases_done": [], "error": None,
            "error_detail": None, "folder": None, "started_at": None,
            "finished_at": None, "run_id": None, "phase_timings": {},
        }

    # ---------- public API ----------
    def status(self):
        with self.lock:
            s = dict(self.state)
            s["all_phases"] = PHASE_NAMES
            s["seq"] = self._seq
            s["log"] = [ln["t"] for ln in list(self.log)[-200:]]
        try:    # DB counts on a throwaway read connection (outside the lock)
            c = db.connect(self.db_path)

            def one(q):
                return c.execute(q).fetchone()[0]
            s["faces_found"] = one("SELECT COUNT(*) FROM faces")
            s["index_total"] = one("SELECT COUNT(*) FROM images")
            s["index_done"] = one("SELECT COUNT(*) FROM images WHERE processed!=0")
            s["errors"] = one("SELECT COUNT(*) FROM images WHERE processed=2")
            s["recent_face_ids"] = [r[0] for r in
                                    c.execute("SELECT id FROM faces ORDER BY id DESC LIMIT 24")]
            c.close()
        except Exception:
            pass
        return s

    def log_lines(self, since=0):
        since = int(since or 0)
        with self.lock:
            return [[ln["n"], ln["t"]] for ln in self.log if ln["n"] > since]

    def stream(self, since=0):
        """Generator of (seq, text) lines for SSE; ends when the run finishes and
        the buffer past `since` is drained."""
        last = int(since or 0)
        while True:
            with self.lock:
                new = [[ln["n"], ln["t"]] for ln in self.log if ln["n"] > last]
                running = self.state["running"]
            for n, t in new:
                last = n
                yield n, t
            if not running and not new:
                break
            self._event.wait(timeout=1.0)
            self._event.clear()

    def runs(self, limit=20):
        try:
            c = db.connect(self.db_path)
            rows = c.execute(
                """SELECT id, started_at, finished_at, status, phases, error
                   FROM runs ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
            c.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def run_log_path(self, run_id):
        try:
            c = db.connect(self.db_path)
            r = c.execute("SELECT log_file FROM runs WHERE id=?", (int(run_id),)).fetchone()
            c.close()
            return r["log_file"] if r and r["log_file"] else None
        except Exception:
            return None

    def reconcile(self):
        """Mark any run left 'running' by a crashed/restarted server as interrupted."""
        if self._reconciled:
            return
        self._reconciled = True
        try:
            c = db.connect(self.db_path)
            c.execute("UPDATE runs SET status='interrupted', finished_at=COALESCE(finished_at, ?) "
                      "WHERE status='running'", (time.time(),))
            c.commit()
            c.close()
        except Exception:
            pass

    def start(self, folder, phases=None, flags=None):
        folder = (folder or "").strip()
        with self.lock:
            if self.state["running"]:
                return False, "a run is already in progress"
            if not folder or not os.path.isdir(folder):
                return False, f"folder not found: {folder}"
            self._phases = [p for p in PHASES if phases is None or p[0] in phases]
            self._flags = flags or {}
            self._cancelled = False
            self._stalled = False
            self.log.clear()
            self._seq = 0
            self.run_id = int(time.time() * 1000)
            self._open_log(self.run_id)
            self.state.update(running=True, phase=None, phases_done=[], error=None,
                              error_detail=None, folder=folder, started_at=time.time(),
                              finished_at=None, run_id=self.run_id, phase_timings={})
        self.reconcile()
        self._record_run_start(self.run_id, folder, [p[0] for p in self._phases], self._log_file)
        threading.Thread(target=self._run, args=(folder,), daemon=True).start()
        return True, "started"

    def cancel(self):
        with self.lock:
            if not self.state["running"]:
                return False, "no run in progress"
            self._cancelled = True
            proc = self._proc
        self._log("!! stop requested")
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
        return True, "stopping"

    # ---------- internals ----------
    def _open_log(self, run_id):
        self._log_file = None
        self._fh = None
        target = None
        if self.runs_dir:
            try:
                os.makedirs(self.runs_dir, exist_ok=True)
                target = os.path.join(self.runs_dir, f"{run_id}.log")
            except OSError:
                target = self.log_path
        else:
            target = self.log_path
        if target:
            try:
                self._fh = open(target, "a", buffering=1, encoding="utf-8")
                self._log_file = target
            except OSError:
                self._fh = None

    def _run(self, folder):
        threading.Thread(target=self._watch, daemon=True).start()
        status = "done"
        try:
            for name, module, build_args in self._phases:
                with self.lock:
                    self.state["phase"] = name
                self._log(f"=== phase: {name} ===")
                _log_mod.info("phase %s started", name)
                t0 = time.monotonic()
                self._last_output = time.monotonic()
                cmd = [sys.executable, "-m", module, *build_args(folder, self.db_path),
                       *self._flags.get(name, [])]
                proc = subprocess.Popen(
                    cmd, cwd=PROJECT_DIR, text=True, bufsize=1,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                with self.lock:
                    self._proc = proc
                tail = deque(maxlen=ERROR_TAIL)
                for line in proc.stdout:
                    line = line.rstrip()
                    self._last_output = time.monotonic()
                    tail.append(line)
                    self._log(line)
                proc.wait()
                dt = time.monotonic() - t0
                with self.lock:
                    self.state["phase_timings"][name] = round(dt, 1)
                    self._proc = None
                self._log(f"phase {name} finished in {dt:.1f}s (exit {proc.returncode})")
                _log_mod.info("phase %s finished in %.1fs (exit %d)", name, dt, proc.returncode)
                if self._cancelled:
                    status = "cancelled"
                    self._set_error("run stopped — phase stalled" if self._stalled else "run stopped", None)
                    break
                if proc.returncode != 0:
                    status = "error"
                    self._set_error(f"phase '{name}' exited with code {proc.returncode}", "\n".join(tail))
                    break
                with self.lock:
                    self.state["phases_done"].append(name)
            else:
                self._log("all phases complete")
        except Exception as e:  # noqa: BLE001
            status = "error"
            self._set_error(str(e), None)
        finally:
            err = self.state.get("error")
            with self.lock:
                self.state.update(running=False, phase=None, finished_at=time.time())
            self._record_run_end(self.run_id, status, err)
            self._close_log()
            self._event.set()

    def _watch(self):
        """Kill a phase that produces no output for too long (e.g. a hung model
        download), so the UI fails instead of hanging on 'Running' forever."""
        timeout = getattr(config, "RUN_PHASE_STALL_TIMEOUT_S", 1800)
        while True:
            with self.lock:
                running = self.state["running"]
                proc = self._proc
                cancelled = self._cancelled
                last = self._last_output
            if not running:
                return
            if proc and not cancelled and last and (time.monotonic() - last) > timeout:
                with self.lock:
                    self._cancelled = True
                    self._stalled = True
                self._log(f"!! no output for {timeout}s — terminating stalled phase")
                try:
                    proc.terminate()
                except Exception:
                    pass
                return
            time.sleep(5)

    def _set_error(self, msg, detail):
        with self.lock:
            self.state["error"] = msg
            if detail:
                self.state["error_detail"] = detail
        self._log(f"!! {msg}")

    def _log(self, msg):
        if not msg:
            return
        ts = time.time()
        with self.lock:
            self._seq += 1
            self.log.append({"n": self._seq, "ts": ts, "t": msg})
            if self._fh:
                try:
                    self._fh.write(time.strftime("%H:%M:%S ", time.localtime(ts)) + msg + "\n")
                except (OSError, ValueError):
                    pass
        self._event.set()

    def _close_log(self):
        with self.lock:
            fh, src = self._fh, self._log_file
            self._fh = None
        if fh:
            try:
                fh.close()
            except OSError:
                pass
        # mirror the latest run to <slug>/run.log for back-compat / quick tailing
        if src and self.log_path and os.path.abspath(src) != os.path.abspath(self.log_path):
            try:
                shutil.copy2(src, self.log_path)
            except OSError:
                pass

    def _record_run_start(self, run_id, folder, phases, log_file):
        try:
            c = db.connect(self.db_path)
            c.execute(
                """INSERT OR REPLACE INTO runs(id, started_at, finished_at, status, phases, error, log_file)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id, time.time(), None, "running", ",".join(phases), None, log_file or ""))
            c.commit()
            c.close()
        except Exception:
            pass

    def _record_run_end(self, run_id, status, error):
        if run_id is None:
            return
        try:
            c = db.connect(self.db_path)
            c.execute("UPDATE runs SET finished_at=?, status=?, error=? WHERE id=?",
                      (time.time(), status, error, run_id))
            c.commit()
            c.close()
        except Exception:
            pass


_runners = {}


def get_runner(slug, db_path, log_path=None, runs_dir=None):
    r = _runners.get(slug)
    if r is None:
        r = Runner(db_path, log_path, runs_dir)
        r.reconcile()
        _runners[slug] = r
    return r
