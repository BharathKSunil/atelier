"""Learned pick-ranking head (scaffold): pair mining, training that beats the warm
start, the graceful-degrade floor, and model persistence. Signal lives only in the
embedding so the warm-start (the heuristic score) can't separate — proving the head
actually learns."""

import numpy as np

from atelier import db, learning


def _seed(conn, n_series=15, frames=4):
    """Each series has one winner (embedding dim 0 hot) vs losers (dim 1 hot); the
    print_score is equal across the burst so the warm-start can't tell them apart. A
    'good' feedback verdict on each winner yields (winner, sibling) preference pairs."""
    iid = 0
    for s in range(n_series):
        conn.execute("INSERT INTO series(id, frame_count) VALUES(?,?)", (s, frames))
        winner = None
        for fnum in range(frames):
            iid += 1
            e = np.zeros(learning.config.LEARN_EMB_DIM, dtype=np.float32)
            e[0 if fnum == 0 else 1] = 1.0  # winner hot on dim 0, losers on dim 1
            conn.execute(
                """INSERT INTO images(id, path, processed, series_id, print_score, global_embedding)
                   VALUES(?,?,1,?,?,?)""",
                (iid, f"/{iid}.jpg", s, 0.5, e.tobytes()),
            )
            if fnum == 0:
                winner = iid
        conn.execute(
            "INSERT INTO pick_feedback(pick_type, auto_image_id, verdict, created_at) VALUES('print',?,'good',0)",
            (winner,),
        )
    conn.commit()


def test_build_pairs_winner_over_siblings(tmp_path):
    conn = db.connect(str(tmp_path / "f.db"))
    _seed(conn, n_series=3, frames=4)
    pairs = learning.build_pairs(conn, "print")
    assert len(pairs) == 3 * 3  # 3 siblings per winner
    # every pair is (winner, loser) and winner/loser are distinct
    assert all(w != l for w, l in pairs)


def test_learns_embedding_signal_beyond_warmstart(tmp_path):
    conn = db.connect(str(tmp_path / "f.db"))
    _seed(conn, n_series=15)
    pairs = learning.build_pairs(conn, "print")
    assert len(pairs) >= learning.config.LEARN_MIN_PAIRS
    xw, xl = learning.assemble(conn, pairs)
    warm = learning.warm_start("print")
    warm_acc = float(((xw - xl) @ warm > 0).mean())
    w, acc = learning.train(xw, xl, warm)
    assert warm_acc < 0.6  # equal print_score -> the heuristic can't separate
    assert acc > 0.9  # the head learned the embedding signal
    learning.score_all(conn, w)
    win, los = pairs[0]
    sw = conn.execute("SELECT learned_score FROM images WHERE id=?", (win,)).fetchone()[0]
    sl = conn.execute("SELECT learned_score FROM images WHERE id=?", (los,)).fetchone()[0]
    assert sw > sl


def test_refuses_below_min_pairs(tmp_path):
    conn = db.connect(str(tmp_path / "f.db"))
    _seed(conn, n_series=2)  # 2*3 = 6 pairs, below the floor
    res = learning.fit(conn, "print", now=0.0)
    assert res["trained"] is False
    assert res["n_pairs"] < learning.config.LEARN_MIN_PAIRS
    n = conn.execute("SELECT COUNT(*) FROM images WHERE learned_score IS NOT NULL").fetchone()[0]
    assert n == 0  # heuristic kept, nothing written


def test_fit_persists_and_reloads_model(tmp_path):
    conn = db.connect(str(tmp_path / "f.db"))
    _seed(conn, n_series=15)
    res = learning.fit(conn, "print", now=123.0)
    assert res["trained"] and res["train_acc"] > 0.9
    w = learning.load_model(conn, "print")
    assert w is not None and w.shape[0] == learning.FEATURE_DIM
    m = conn.execute("SELECT n_pairs, trained_at FROM learned_models WHERE pick_type='print'").fetchone()
    assert m["trained_at"] == 123.0 and m["n_pairs"] >= learning.config.LEARN_MIN_PAIRS
    # re-fit overwrites the single per-pick row (UNIQUE(pick_type))
    learning.fit(conn, "print", now=200.0)
    assert conn.execute("SELECT COUNT(*) FROM learned_models").fetchone()[0] == 1
