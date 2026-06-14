"""Per-project background pipeline runner. Runs the four phase scripts as
sequential subprocesses in a daemon thread; exposes rich live status and tees
output to a per-project log file.
"""
import os
import subprocess
import sys
import threading
import time

from . import db
from .logsetup import get_logger

_log_mod = get_logger("atelier.runner")

PHASES = [
    ("index",   "01_index.py", lambda folder, dbp: ["--photos", folder, "--db", dbp]),
    ("cluster", "02_cluster_persons.py", lambda folder, dbp: ["--db", dbp]),
    ("series",  "02b_group_series.py", lambda folder, dbp: ["--db", dbp]),
    ("score",   "03_score.py", lambda folder, dbp: ["--db", dbp]),
]
PHASE_NAMES = [p[0] for p in PHASES]
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Runner:
    def __init__(self, db_path, log_path=None):
        self.db_path = db_path
        self.log_path = log_path
        self.lock = threading.Lock()
        self.log = []
        self._phases = PHASES
        self._flags = {}
        self.state = {
            "running": False, "phase": None, "phases_done": [], "error": None,
            "folder": None, "started_at": None, "finished_at": None,
        }

    def status(self):
        s = dict(self.state)
        s["all_phases"] = PHASE_NAMES
        s["log"] = self.log[-60:]
        try:
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

    def start(self, folder, phases=None, flags=None):
        folder = (folder or "").strip()
        with self.lock:
            if self.state["running"]:
                return False, "a run is already in progress"
            if not folder or not os.path.isdir(folder):
                return False, f"folder not found: {folder}"
            self._phases = [p for p in PHASES if phases is None or p[0] in phases]
            self._flags = flags or {}
            self.log = []
            self.state.update(running=True, phase=None, phases_done=[], error=None,
                              folder=folder, started_at=time.time(), finished_at=None)
        threading.Thread(target=self._run, args=(folder,), daemon=True).start()
        return True, "started"

    def _run(self, folder):
        if self.log_path:
            try:
                open(self.log_path, "w").close()
            except OSError:
                pass
        try:
            for name, script, build_args in self._phases:
                self.state["phase"] = name
                self._log(f"=== phase: {name} ===")
                _log_mod.info("phase %s started", name)
                t0 = time.monotonic()
                cmd = [sys.executable, script, *build_args(folder, self.db_path),
                       *self._flags.get(name, [])]
                proc = subprocess.Popen(
                    cmd, cwd=PROJECT_DIR, text=True, bufsize=1,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                for line in proc.stdout:
                    self._log(line.rstrip())
                proc.wait()
                dt = time.monotonic() - t0
                self._log(f"phase {name} finished in {dt:.1f}s (exit {proc.returncode})")
                _log_mod.info("phase %s finished in %.1fs (exit %d)", name, dt, proc.returncode)
                if proc.returncode != 0:
                    self.state["error"] = f"phase '{name}' exited with code {proc.returncode}"
                    self._log(f"!! {self.state['error']}")
                    break
                self.state["phases_done"].append(name)
            else:
                self._log("all phases complete")
        except Exception as e:  # noqa: BLE001
            self.state["error"] = str(e)
            self._log(f"!! {e}")
        finally:
            self.state.update(running=False, phase=None, finished_at=time.time())

    def _log(self, msg):
        if not msg:
            return
        self.log.append(msg)
        if self.log_path:
            try:
                with open(self.log_path, "a") as f:
                    f.write(msg + "\n")
            except OSError:
                pass


_runners = {}


def get_runner(slug, db_path, log_path=None):
    r = _runners.get(slug)
    if r is None:
        r = Runner(db_path, log_path)
        _runners[slug] = r
    return r
