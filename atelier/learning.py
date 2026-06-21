"""Learned pick-ranking head — a SCAFFOLD, pure numpy (no torch).

A thin logistic RankNet correction over the deterministic per-image signals plus the
DINOv2 global embedding. It is:
  * warm-started from the current heuristic (weight 1.0 on the pick's own score column,
    0 elsewhere) — so an untrained model ranks exactly like today's picker;
  * L2-regularized TOWARD that warm-start — so with few labels it barely moves, and
    only as feedback accrues does it diverge ("degrades gracefully below ~100 labels");
  * trained on within-burst preference PAIRS mined from `pick_feedback` + bucket keeps.

Predictions are written to images.learned_score (heuristic columns untouched, so the
add-on is reversible). The model is persisted in the learned_models table. Training is
driven offline by `python -m atelier.pipeline.learn`.
"""

import json
import time

import numpy as np

from . import config

# Per-image scalar features, fixed order; the L2-normalized embedding is appended.
SCALAR_FEATURES = [
    "print_score", "moment_score", "comp_score", "candid_score", "cohesion", "joy",
    "aesthetic_score", "global_sharpness", "exposure_score", "eyes_open_frac",
    "smile_frac", "front_frac", "gaze_frac", "bokeh", "skin_exposure", "contrast",
    "subject_size", "warmth", "clutter", "symmetry",
]  # fmt: skip

# Which scalar feature each pick's warm-start anchors on (mirrors the read-time picker).
PICK_ANCHOR = {
    "print": "print_score",
    "moment": "moment_score",
    "everyone": "cohesion",
    "smile": "joy",
    "candid": "candid_score",
    "aesthetic": "aesthetic_score",
}

FEATURE_DIM = len(SCALAR_FEATURES) + config.LEARN_EMB_DIM


def emb_from_buf(buf):
    return np.frombuffer(buf, dtype=np.float32).astype(np.float64) if buf else None


def _val(row, key):
    try:
        v = row[key]
    except (IndexError, KeyError):
        return 0.0
    return float(v) if v is not None else 0.0


def feature_row(img_row, emb):
    """Assemble one image's feature vector: [scalar signals | unit-norm embedding]."""
    scal = np.array([_val(img_row, k) for k in SCALAR_FEATURES], dtype=np.float64)
    e = np.zeros(config.LEARN_EMB_DIM, dtype=np.float64)
    if emb is not None and np.asarray(emb).shape[0] == config.LEARN_EMB_DIM:
        e = np.asarray(emb, dtype=np.float64)
        n = float(np.linalg.norm(e))
        if n > 1e-9:
            e = e / n
    return np.concatenate([scal, e])


def warm_start(pick_type):
    """Weight 1.0 on the pick's own score column, 0 elsewhere — so the untrained model
    reproduces the current heuristic ranking exactly."""
    w = np.zeros(FEATURE_DIM, dtype=np.float64)
    anchor = PICK_ANCHOR.get(pick_type, "print_score")
    w[SCALAR_FEATURES.index(anchor)] = 1.0
    return w


# ----------------------------------------------------------------- pair mining
def _series_of(conn, image_id):
    r = conn.execute("SELECT series_id FROM images WHERE id=?", (image_id,)).fetchone()
    return r["series_id"] if r else None


def _siblings(conn, series_id, exclude_id):
    if series_id is None:
        return []
    return [
        r["id"]
        for r in conn.execute("SELECT id FROM images WHERE series_id=? AND id<>?", (series_id, exclude_id))
    ]


def _in_any_bucket(conn, image_id):
    return conn.execute("SELECT 1 FROM bucket_items WHERE image_id=? LIMIT 1", (image_id,)).fetchone() is not None


def build_pairs(conn, pick_type="print"):
    """(winner_id, loser_id) preference pairs — winner should rank ABOVE loser.
      * feedback 'good'  -> the auto pick beats its same-series siblings
      * feedback 'bad'   -> the user's better_image_id beats the auto pick
      * bucket keep      -> a bucketed frame beats a same-series sibling in NO bucket
    Deduplicated; self-pairs dropped."""
    pairs = set()
    for fb in conn.execute(
        "SELECT auto_image_id, verdict, better_image_id FROM pick_feedback WHERE pick_type=?", (pick_type,)
    ):
        auto = fb["auto_image_id"]
        if fb["verdict"] == "good":
            for sib in _siblings(conn, _series_of(conn, auto), auto):
                pairs.add((auto, sib))
        elif fb["verdict"] == "bad" and fb["better_image_id"]:
            pairs.add((fb["better_image_id"], auto))
    for b in conn.execute(
        """SELECT DISTINCT bi.image_id AS kept, i.series_id AS sid
               FROM bucket_items bi JOIN images i ON i.id=bi.image_id
               WHERE i.series_id IS NOT NULL"""
    ):
        for sib in _siblings(conn, b["sid"], b["kept"]):
            if not _in_any_bucket(conn, sib):
                pairs.add((b["kept"], sib))
    return [(w, l) for (w, l) in pairs if w != l]


def assemble(conn, pairs):
    """Build the (winner, loser) feature matrices for a list of id pairs."""
    cache = {}

    def feat(iid):
        if iid not in cache:
            row = conn.execute("SELECT * FROM images WHERE id=?", (iid,)).fetchone()
            cache[iid] = feature_row(row, emb_from_buf(row["global_embedding"])) if row else np.zeros(FEATURE_DIM)
        return cache[iid]

    xw = np.array([feat(w) for w, _ in pairs], dtype=np.float64)
    xl = np.array([feat(l) for _, l in pairs], dtype=np.float64)
    return xw, xl


# ----------------------------------------------------------------- training
def train(xw, xl, warm, l2=None, lr=None, epochs=None):
    """Logistic RankNet: maximize sigma(w·(x_w - x_l)) with an L2 pull toward `warm`.
    Returns (weights, train_ranking_accuracy)."""
    l2 = config.LEARN_L2 if l2 is None else l2
    lr = config.LEARN_LR if lr is None else lr
    epochs = config.LEARN_EPOCHS if epochs is None else epochs
    d = xw - xl
    if d.ndim != 2 or d.shape[0] == 0:
        return warm.copy(), 0.0
    w = warm.copy()
    for _ in range(epochs):
        p = 1.0 / (1.0 + np.exp(-(d @ w)))  # P(winner ranked above loser)
        grad = -(d.T @ (1.0 - p)) / len(d) + l2 * (w - warm)
        w -= lr * grad
    acc = float((d @ w > 0).mean())
    return w, acc


def predict(img_row, emb, w):
    return float(feature_row(img_row, emb) @ w)


def score_all(conn, w):
    """Write learned_score for every processed image."""
    for im in conn.execute("SELECT * FROM images WHERE processed=1"):
        conn.execute(
            "UPDATE images SET learned_score=? WHERE id=?",
            (predict(im, emb_from_buf(im["global_embedding"]), w), im["id"]),
        )
    conn.commit()


# ----------------------------------------------------------------- persistence
def save_model(conn, pick_type, w, n_pairs, train_acc, now):
    conn.execute(
        """INSERT INTO learned_models(pick_type, weights, feature_names, n_pairs, train_acc, trained_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(pick_type) DO UPDATE SET
             weights=excluded.weights, feature_names=excluded.feature_names,
             n_pairs=excluded.n_pairs, train_acc=excluded.train_acc, trained_at=excluded.trained_at""",
        (
            pick_type,
            np.asarray(w, dtype=np.float64).tobytes(),
            json.dumps(SCALAR_FEATURES + [f"emb{i}" for i in range(config.LEARN_EMB_DIM)]),
            int(n_pairs),
            float(train_acc),
            float(now),
        ),
    )
    conn.commit()


def load_model(conn, pick_type):
    r = conn.execute("SELECT weights FROM learned_models WHERE pick_type=?", (pick_type,)).fetchone()
    return np.frombuffer(r["weights"], dtype=np.float64) if r else None


def fit(conn, pick_type="print", now=None):
    """End-to-end: mine pairs, (maybe) train, write learned_score + persist. Returns a
    summary dict. Below LEARN_MIN_PAIRS it refuses to train and keeps the heuristic."""
    now = time.time() if now is None else now
    pairs = build_pairs(conn, pick_type)
    if len(pairs) < config.LEARN_MIN_PAIRS:
        return {"trained": False, "n_pairs": len(pairs), "reason": "too few labels"}
    xw, xl = assemble(conn, pairs)
    w, acc = train(xw, xl, warm_start(pick_type))
    score_all(conn, w)
    save_model(conn, pick_type, w, len(pairs), acc, now)
    return {"trained": True, "n_pairs": len(pairs), "train_acc": acc}
