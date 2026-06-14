import os
import tempfile

from facelib import db


def test_init_creates_tables():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = db.init_db(path)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"images", "faces", "persons", "series"} <= names
    finally:
        conn.close()
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(path + ext):
                os.remove(path + ext)


def test_insert_and_query_roundtrip():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = db.init_db(path)
        conn.execute("INSERT INTO images(path, processed) VALUES('/a/b.jpg', 1)")
        conn.commit()
        row = conn.execute("SELECT path, processed FROM images").fetchone()
        assert row["path"] == "/a/b.jpg"
        assert row["processed"] == 1
    finally:
        conn.close()
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(path + ext):
                os.remove(path + ext)
