"""SQLite schema, connection, and migrations.

Base schema = v0. Schema growth happens via MIGRATIONS (PRAGMA user_version),
applied automatically on connect() so existing project DBs upgrade in place.
"""

import sqlite3

BASE_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  file_size INTEGER,
  width INTEGER, height INTEGER,
  taken_at REAL,
  exif_time INTEGER DEFAULT 0,
  sub_sec INTEGER,
  camera TEXT,
  orientation INTEGER,
  global_embedding BLOB,
  global_sharpness REAL,
  exposure_score REAL,
  series_id INTEGER,
  print_score REAL,
  is_best_in_series INTEGER DEFAULT 0,
  processed INTEGER DEFAULT 0,
  error_msg TEXT
);

CREATE TABLE IF NOT EXISTS faces (
  id INTEGER PRIMARY KEY,
  image_id INTEGER NOT NULL REFERENCES images(id),
  face_index INTEGER,
  bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL,
  confidence REAL,
  embedding BLOB,
  thumbnail BLOB,
  face_sharpness REAL,
  eye_open REAL,
  smile REAL,
  frontality REAL,
  quality_score REAL,
  person_id INTEGER,
  is_best INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS persons (
  id INTEGER PRIMARY KEY,
  display_name TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS series (
  id INTEGER PRIMARY KEY,
  frame_count INTEGER,
  best_image_id INTEGER,
  time_start REAL, time_end REAL
);

CREATE INDEX IF NOT EXISTS idx_faces_image ON faces(image_id);
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS idx_images_series ON images(series_id);
CREATE INDEX IF NOT EXISTS idx_images_processed ON images(processed);
"""

# Each migration: (version, [sql statements]). Applied in order when DB is behind.
MIGRATIONS = [
    # v1 — Phase 0: manual identity overrides, anchored on the only re-run-stable
    # key (faces.id). group_key identifies a forced identity; kind = merge|reassign|split.
    (
        1,
        [
            """CREATE TABLE IF NOT EXISTS person_overrides (
             face_id INTEGER PRIMARY KEY REFERENCES faces(id),
             group_key TEXT NOT NULL,
             kind TEXT,
             display_name TEXT,
             created_at REAL
           )""",
            "CREATE INDEX IF NOT EXISTS idx_overrides_group ON person_overrides(group_key)",
        ],
    ),
    # v2 — Phase 1: persisted image thumbnails + composite indices matching server sorts.
    (
        2,
        [
            "ALTER TABLE images ADD COLUMN thumbnail BLOB",
            "CREATE INDEX IF NOT EXISTS idx_faces_person_best ON faces(person_id, is_best DESC, quality_score DESC)",
            "CREATE INDEX IF NOT EXISTS idx_series_frame_count ON series(frame_count DESC)",
            "CREATE INDEX IF NOT EXISTS idx_images_series_score ON images(series_id, print_score DESC)",
        ],
    ),
    # v3 — Phase 2: multiple criteria-based picks per series; face_count for aggregation.
    (
        3,
        [
            """CREATE TABLE IF NOT EXISTS picks (
             id INTEGER PRIMARY KEY,
             series_id INTEGER REFERENCES series(id),
             image_id INTEGER REFERENCES images(id),
             pick_type TEXT NOT NULL,
             rank INTEGER DEFAULT 0,
             reason TEXT,
             source TEXT DEFAULT 'auto',
             UNIQUE(series_id, pick_type)
           )""",
            "CREATE INDEX IF NOT EXISTS idx_picks_series ON picks(series_id)",
            "ALTER TABLE images ADD COLUMN face_count INTEGER DEFAULT 0",
        ],
    ),
    # v4 — Phase 4: aesthetic score + raw sharpness for event-adaptive normalization.
    (
        4,
        [
            "ALTER TABLE images ADD COLUMN aesthetic_score REAL",
            "ALTER TABLE images ADD COLUMN global_sharpness_raw REAL",
            "ALTER TABLE faces ADD COLUMN face_sharpness_raw REAL",
        ],
    ),
    # v5 — re-anchor picks on the STABLE key (image_id). series_id is rebuilt by
    # 02b every run, so picks keyed on it broke on regroup (and FK-blocked the
    # series rebuild). Now only manual picks are stored; auto picks are derived at
    # read time from per-image scores. candid_score is stored alongside.
    (
        5,
        [
            "DROP TABLE IF EXISTS picks",
            """CREATE TABLE picks (
             id INTEGER PRIMARY KEY,
             image_id INTEGER NOT NULL REFERENCES images(id),
             pick_type TEXT NOT NULL,
             source TEXT DEFAULT 'manual',
             reason TEXT,
             UNIQUE(image_id, pick_type)
           )""",
            "CREATE INDEX IF NOT EXISTS idx_picks_image ON picks(image_id)",
            "ALTER TABLE images ADD COLUMN candid_score REAL",
        ],
    ),
    # v6 — persistent run history: each pipeline run is recorded so history and
    # per-run logs survive a server restart (status reconciled to 'interrupted').
    (
        6,
        [
            """CREATE TABLE IF NOT EXISTS runs (
             id INTEGER PRIMARY KEY,
             started_at REAL,
             finished_at REAL,
             status TEXT,
             phases TEXT,
             error TEXT,
             log_file TEXT
           )""",
        ],
    ),
    # v7 — user-defined buckets: named collections an image can belong to many of
    # (e.g. "Social media", "Candids", "Private"). Separate from the print list.
    (
        7,
        [
            """CREATE TABLE IF NOT EXISTS buckets (
             id INTEGER PRIMARY KEY,
             name TEXT NOT NULL,
             color TEXT,
             sort_order INTEGER DEFAULT 0,
             created_at REAL
           )""",
            """CREATE TABLE IF NOT EXISTS bucket_items (
             bucket_id INTEGER NOT NULL REFERENCES buckets(id) ON DELETE CASCADE,
             image_id INTEGER NOT NULL REFERENCES images(id),
             added_at REAL,
             PRIMARY KEY (bucket_id, image_id)
           )""",
            "CREATE INDEX IF NOT EXISTS idx_bucket_items_image ON bucket_items(image_id)",
        ],
    ),
]

SCHEMA_VERSION = MIGRATIONS[-1][0] if MIGRATIONS else 0


def _apply_migrations(conn):
    cur = conn.execute("PRAGMA user_version").fetchone()[0]
    if cur >= SCHEMA_VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute("PRAGMA user_version").fetchone()[0]  # re-read under lock
        for version, statements in MIGRATIONS:
            if version <= cur:
                continue
            for sql in statements:
                conn.execute(sql)
            conn.execute(f"PRAGMA user_version={version}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _raw_connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def connect(path):
    conn = _raw_connect(path)
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        conn.executescript(BASE_SCHEMA)  # self-heal: ensure base tables before ALTERs
        conn.commit()
    _apply_migrations(conn)
    return conn


def init_db(path):
    conn = _raw_connect(path)
    conn.executescript(BASE_SCHEMA)
    conn.commit()
    _apply_migrations(conn)
    return conn
