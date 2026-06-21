"""SQLite schema, connection, and migrations.

Base schema = v0. Schema growth happens via MIGRATIONS (PRAGMA user_version),
applied automatically on connect() so existing project DBs upgrade in place.
"""

import re
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
    # v8 — index the bucket-browse sort (WHERE bucket_id=? ORDER BY added_at DESC, image_id)
    # so paging a large bucket doesn't filesort the whole membership each page.
    (
        8,
        [
            "CREATE INDEX IF NOT EXISTS idx_bucket_items_bucket_added ON bucket_items(bucket_id, added_at, image_id)",
        ],
    ),
    # v9 — dogfooding feedback: capture verdicts on the auto criterion-picks
    # (group/candid/aesthetic) so the scorer can be retrained. Anchored on the
    # auto image_id + pick_type (the only re-run-stable key — series ids are rebuilt
    # every 02b run), with an optional "the better frame was X" correction. Also a
    # per-series reviewed flag so the cull position/progress survives reload.
    (
        9,
        [
            """CREATE TABLE IF NOT EXISTS pick_feedback (
             id INTEGER PRIMARY KEY,
             pick_type TEXT NOT NULL,
             auto_image_id INTEGER NOT NULL REFERENCES images(id),
             verdict TEXT NOT NULL,                 -- 'good' | 'bad'
             better_image_id INTEGER REFERENCES images(id),
             note TEXT,
             created_at REAL,
             UNIQUE(pick_type, auto_image_id)
           )""",
            "CREATE INDEX IF NOT EXISTS idx_feedback_auto ON pick_feedback(auto_image_id)",
            "ALTER TABLE series ADD COLUMN reviewed_at REAL",
        ],
    ),
    # v10 — richer per-image quality metrics ("all the tags"). Computed in the score
    # phase from already-stored per-face signals (no re-index). Back context-aware
    # picks (everyone/smile/moment) + the plain-language fraction tags shown in Review.
    (
        10,
        [
            "ALTER TABLE images ADD COLUMN moment_score REAL",  # decisive frame, soft eyes
            "ALTER TABLE images ADD COLUMN cohesion REAL",  # 'everyone engaged'
            "ALTER TABLE images ADD COLUMN joy REAL",  # biggest smile in the frame
            "ALTER TABLE images ADD COLUMN comp_score REAL",  # crop-safety + thirds + headroom
            "ALTER TABLE images ADD COLUMN eyes_open_frac REAL",  # fraction of faces eyes-open
            "ALTER TABLE images ADD COLUMN smile_frac REAL",  # fraction smiling
            "ALTER TABLE images ADD COLUMN front_frac REAL",  # fraction facing the camera
            "ALTER TABLE images ADD COLUMN eyes_min REAL",  # worst eye (group-strict signal)
            "ALTER TABLE images ADD COLUMN subject_size REAL",  # largest face area fraction
        ],
    ),
    # v11 — the print list IS a bucket. Buckets gain a role + a per-project default
    # (the spacebar target). The old print picks (pick_type='print') migrate into a
    # default "Print list" bucket so everything is one unified collection model.
    (
        11,
        [
            "ALTER TABLE buckets ADD COLUMN role TEXT",
            "ALTER TABLE buckets ADD COLUMN is_default INTEGER DEFAULT 0",
            """INSERT INTO buckets(name, color, role, is_default, sort_order, created_at)
               SELECT 'Print list', '#c64a5b', 'print', 1, -1, CAST(strftime('%s','now') AS REAL)
               WHERE NOT EXISTS (SELECT 1 FROM buckets WHERE role='print')""",
            """INSERT OR IGNORE INTO bucket_items(bucket_id, image_id, added_at)
               SELECT (SELECT id FROM buckets WHERE role='print' LIMIT 1), image_id,
                 CAST(strftime('%s','now') AS REAL)
               FROM picks WHERE pick_type='print'""",
            "DELETE FROM picks WHERE pick_type='print'",
        ],
    ),
    # v12 — P1 face signals from MediaPipe blendshapes + head-pose transform. Per-eye
    # blink (independent L/R), head-pose Euler (yaw/pitch/roll), gaze-at-camera, and a
    # Duchenne (genuine) smile signal. Populated in the score phase; null when the
    # landmarker/blendshapes are unavailable (graceful fallback to EAR/geometry).
    (
        12,
        [
            "ALTER TABLE faces ADD COLUMN eye_left REAL",  # left-eye openness (1 - blink)
            "ALTER TABLE faces ADD COLUMN eye_right REAL",  # right-eye openness
            "ALTER TABLE faces ADD COLUMN yaw REAL",  # head turn L/R (deg)
            "ALTER TABLE faces ADD COLUMN pitch REAL",  # head nod up/down (deg)
            "ALTER TABLE faces ADD COLUMN roll REAL",  # head tilt (deg)
            "ALTER TABLE faces ADD COLUMN gaze REAL",  # looking-at-camera [0,1]
            "ALTER TABLE faces ADD COLUMN genuine_smile REAL",  # Duchenne smile [0,1]
            "ALTER TABLE images ADD COLUMN gaze_frac REAL",  # fraction making eye contact
        ],
    ),
    # v13 — P1 light / color / focus signals. Per-image scalars computed in the score
    # phase from the stored thumbnails (no originals re-read); bg_sharpness_raw is the
    # one exception, measured in the index phase (needs the full frame) and populated
    # on the next re-index. faces.face_exposure caches the per-face skin brightness.
    (
        13,
        [
            "ALTER TABLE faces ADD COLUMN face_exposure REAL",  # per-face skin brightness [0,1]
            "ALTER TABLE images ADD COLUMN highlight_frac REAL",  # blown-highlight area
            "ALTER TABLE images ADD COLUMN shadow_frac REAL",  # crushed-shadow area
            "ALTER TABLE images ADD COLUMN contrast REAL",  # tonal spread
            "ALTER TABLE images ADD COLUMN color_cast REAL",  # global color cast (0=neutral)
            "ALTER TABLE images ADD COLUMN hue_var REAL",  # hue scatter (tempers colorfulness)
            "ALTER TABLE images ADD COLUMN horizon_tilt REAL",  # Dutch tilt (0=level)
            "ALTER TABLE images ADD COLUMN skin_exposure REAL",  # subject/face exposure
            "ALTER TABLE images ADD COLUMN bg_sharpness_raw REAL",  # background acutance (index)
            "ALTER TABLE images ADD COLUMN bokeh REAL",  # subject-vs-bg sharpness
        ],
    ),
    # v14 — P2/P3 scene / focus / dup signals. Per-face awkward-expression flags from
    # the already-extracted blendshapes; per-image scene signals over the thumbnail; a
    # within-burst near-duplicate score from the stored DINOv2 embeddings.
    (
        14,
        [
            "ALTER TABLE faces ADD COLUMN grimace REAL",  # brow/sneer/frown transient
            "ALTER TABLE faces ADD COLUMN mouth_open REAL",  # talking (jaw open, no smile)
            "ALTER TABLE images ADD COLUMN warmth REAL",  # colour temperature (golden hour)
            "ALTER TABLE images ADD COLUMN rim_light REAL",  # backlight / rim halo
            "ALTER TABLE images ADD COLUMN clutter REAL",  # background busy-ness
            "ALTER TABLE images ADD COLUMN symmetry REAL",  # left-right mirror similarity
            "ALTER TABLE images ADD COLUMN motion_blur REAL",  # directional-smear anisotropy
            "ALTER TABLE images ADD COLUMN redundancy REAL",  # within-burst near-dup cosine
        ],
    ),
    # v15 — learned pick-ranking head (scaffold). A thin correction over the per-image
    # signals + the DINOv2 embedding, trained offline from feedback/buckets and written
    # to images.learned_score; the model itself is persisted in learned_models so it can
    # be reloaded/inspected. Heuristic scores stay untouched (a reversible add-on).
    (
        15,
        [
            "ALTER TABLE images ADD COLUMN learned_score REAL",
            """CREATE TABLE IF NOT EXISTS learned_models (
                 id INTEGER PRIMARY KEY,
                 pick_type TEXT NOT NULL UNIQUE,
                 weights BLOB NOT NULL,
                 feature_names TEXT NOT NULL,
                 n_pairs INTEGER,
                 train_acc REAL,
                 trained_at REAL
               )""",
        ],
    ),
    # v16 — record the source folder on each run, so the Run screen's "Source:" line
    # survives a server restart (it was rebuilt from the runs row, which lacked it).
    (
        16,
        [
            "ALTER TABLE runs ADD COLUMN folder TEXT",
        ],
    ),
]

SCHEMA_VERSION = max((v for v, _ in MIGRATIONS), default=0)

_ADD_COL_RE = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+) (.+)", re.I)


def _ensure_columns(conn):
    """Self-heal: ensure every column declared by an ADD COLUMN migration exists,
    independent of user_version. Repairs a DB left partial by the earlier
    migration-ordering bug (a v9 DB that jumped to v11 and skipped v10's columns)."""
    want = {}
    for _, statements in MIGRATIONS:
        for sql in statements:
            m = _ADD_COL_RE.search(sql.strip())
            if m:
                want.setdefault(m.group(1), {})[m.group(2)] = m.group(3).strip()
    changed = False
    for table, cols in want.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, coltype in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
                changed = True
    if changed:
        conn.commit()


def _apply_migrations(conn):
    cur = conn.execute("PRAGMA user_version").fetchone()[0]
    if cur >= SCHEMA_VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute("PRAGMA user_version").fetchone()[0]  # re-read under lock
        for version, statements in sorted(MIGRATIONS, key=lambda m: m[0]):
            if version <= cur:
                continue
            for sql in statements:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError as e:
                    # idempotent ADD COLUMN: a column left by drift is already there
                    if "duplicate column name" in str(e).lower() and "add column" in sql.lower():
                        continue
                    raise
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
    _ensure_columns(conn)  # repair any column drift left by past migration ordering
    return conn


def init_db(path):
    conn = _raw_connect(path)
    conn.executescript(BASE_SCHEMA)
    conn.commit()
    _apply_migrations(conn)
    return conn
