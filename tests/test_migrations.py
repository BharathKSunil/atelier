import sqlite3

from atelier import db


def test_fresh_db_at_latest_version(tmp_path):
    p = str(tmp_path / "x.db")
    db.init_db(p).close()
    c = db.connect(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    cols = {r[1] for r in c.execute("PRAGMA table_info(images)")}
    assert {"thumbnail", "face_count", "aesthetic_score"} <= cols
    tabs = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"person_overrides", "picks"} <= tabs


def test_v0_db_upgrades_in_place(tmp_path):
    p = str(tmp_path / "old.db")
    raw = sqlite3.connect(p)
    raw.executescript(db.BASE_SCHEMA)
    raw.commit()
    raw.close()
    assert sqlite3.connect(p).execute("PRAGMA user_version").fetchone()[0] == 0
    c = db.connect(p)   # connect() must migrate
    assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert "pick_type" in {r[1] for r in c.execute("PRAGMA table_info(picks)")}


def test_migration_is_idempotent(tmp_path):
    p = str(tmp_path / "y.db")
    db.init_db(p).close()
    db.connect(p).close()   # second pass must be a no-op, not an error
    c = db.connect(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
