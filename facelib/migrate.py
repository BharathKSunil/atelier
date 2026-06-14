"""One-time migration of the old flat project layout into the nested one.

Old:  <src>/registry.json, <src>/<slug>.db (+ -wal/-shm), <src>/<slug>.log
New:  <dst>/registry.json, <dst>/<slug>/db.sqlite (+ sidecars), <dst>/<slug>/run.log
"""
import json
import os
import shutil
import sqlite3


def migrate_flat_to_nested(src, dst):
    """Returns the number of projects migrated. Idempotent (no-op if dst already set up)."""
    src_reg = os.path.join(src, "registry.json")
    if not os.path.exists(src_reg):
        return 0
    if os.path.exists(os.path.join(dst, "registry.json")):
        return 0   # already migrated
    try:
        with open(src_reg) as f:
            items = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0

    os.makedirs(dst, exist_ok=True)
    migrated = 0
    for p in items:
        slug = p.get("slug")
        if not slug:
            continue
        out_dir = os.path.join(dst, slug)
        os.makedirs(out_dir, exist_ok=True)
        flat_db = os.path.join(src, f"{slug}.db")
        if os.path.exists(flat_db):
            try:                                   # flush WAL so the copy isn't lossy
                c = sqlite3.connect(flat_db)
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                c.close()
            except Exception:
                pass
            shutil.copy2(flat_db, os.path.join(out_dir, "db.sqlite"))
            for ext in ("-wal", "-shm"):
                if os.path.exists(flat_db + ext):
                    shutil.copy2(flat_db + ext, os.path.join(out_dir, "db.sqlite" + ext))
        flat_log = os.path.join(src, f"{slug}.log")
        if os.path.exists(flat_log):
            shutil.copy2(flat_log, os.path.join(out_dir, "run.log"))
        migrated += 1

    shutil.copy2(src_reg, os.path.join(dst, "registry.json"))
    return migrated
