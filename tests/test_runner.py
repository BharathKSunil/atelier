"""Runner machinery tests: per-run log file, runs-table history, error capture,
and restart reconciliation. Uses a fake subprocess so no ML stack is needed."""

import os
import time

from atelier import db, runner


class FakeProc:
    def __init__(self, lines, rc=0):
        self.stdout = iter(lines)
        self.returncode = rc
        self._rc = rc

    def wait(self):
        self.returncode = self._rc

    def terminate(self):
        self.returncode = -15


def _wait(r, timeout=5):
    t0 = time.time()
    while r.state["running"] and time.time() - t0 < timeout:
        time.sleep(0.02)
    assert not r.state["running"], "run did not finish"


def test_runner_records_run_and_writes_log(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: FakeProc(["hello", "world"], 0))
    db_path = str(tmp_path / "db.sqlite")
    db.init_db(db_path).close()
    r = runner.Runner(db_path, log_path=str(tmp_path / "run.log"), runs_dir=str(tmp_path / "runs"))
    ok, _ = r.start(str(tmp_path))
    assert ok
    _wait(r)
    assert set(r.state["phases_done"]) == set(runner.PHASE_NAMES)
    rows = r.runs()
    assert rows and rows[0]["status"] == "done"
    logf = r.run_log_path(rows[0]["id"])
    assert logf and os.path.exists(logf)
    with open(logf) as f:
        assert "hello" in f.read()


def test_failed_phase_captures_traceback(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: FakeProc(["Traceback (most recent call last):", "ValueError: boom"], 1),
    )
    db_path = str(tmp_path / "db.sqlite")
    db.init_db(db_path).close()
    r = runner.Runner(db_path, runs_dir=str(tmp_path / "runs"))
    r.start(str(tmp_path))
    _wait(r)
    assert r.state["error"] and "exited with code 1" in r.state["error"]
    assert "boom" in (r.state["error_detail"] or "")
    assert r.runs()[0]["status"] == "error"


def test_log_lines_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: FakeProc(["a", "b"], 0))
    db_path = str(tmp_path / "db.sqlite")
    db.init_db(db_path).close()
    r = runner.Runner(db_path, runs_dir=str(tmp_path / "runs"))
    r.start(str(tmp_path))
    _wait(r)
    alllines = r.log_lines(since=0)
    assert alllines, "expected log lines"
    last = alllines[-1][0]
    assert r.log_lines(since=last) == []  # nothing past the cursor


def test_reconcile_marks_running_as_interrupted(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    c = db.init_db(db_path)
    c.execute("INSERT INTO runs(id, started_at, status) VALUES(1, 0, 'running')")
    c.commit()
    c.close()
    runner.Runner(db_path).reconcile()
    c = db.connect(db_path)
    assert c.execute("SELECT status FROM runs WHERE id=1").fetchone()[0] == "interrupted"
    c.close()


def test_hydrate_restores_state_and_log_after_restart(tmp_path, monkeypatch):
    """A run finishes, the process restarts (fresh Runner), and the Run screen must
    still show 'Complete' with the prior log replayed — not a blank state with only
    face counts."""
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: FakeProc(["indexing", "all phases complete"], 0))
    db_path = str(tmp_path / "db.sqlite")
    db.init_db(db_path).close()
    runs_dir = str(tmp_path / "runs")
    r1 = runner.Runner(db_path, log_path=str(tmp_path / "run.log"), runs_dir=runs_dir)
    r1.start(str(tmp_path))
    _wait(r1)
    rid = r1.state["run_id"]

    # simulate a restart: a brand-new runner with an empty in-memory state + log
    runner._runners.clear()
    r2 = runner.get_runner("proj", db_path, log_path=str(tmp_path / "run.log"), runs_dir=runs_dir)
    s = r2.status()
    assert not s["running"]
    assert set(s["phases_done"]) == set(runner.PHASE_NAMES)  # B2: shows Complete, not blank
    assert s["run_id"] == rid
    lines = [t for _, t in r2.log_lines(since=0)]  # B1: log replayed from disk
    assert any("all phases complete" in t for t in lines)
