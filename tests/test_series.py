import numpy as np

from atelier import series


def _n(v):
    v = np.asarray(v, np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def test_burst_close_in_time_and_similar_merges():
    a = {"id": 1, "t": 100.0, "emb": _n([1, 0, 0])}
    b = {"id": 2, "t": 101.0, "emb": _n([0.99, 0.1, 0])}
    m = series.group_series([a, b], 10, 0.88, 0.92)
    assert m[1] == m[2]


def test_far_in_time_and_different_splits():
    a = {"id": 1, "t": 100.0, "emb": _n([1, 0, 0])}
    b = {"id": 2, "t": 100000.0, "emb": _n([0, 1, 0])}
    m = series.group_series([a, b], 10, 0.88, 0.92)
    assert m[1] != m[2]


def test_close_in_time_but_dissimilar_splits():
    a = {"id": 1, "t": 100.0, "emb": _n([1, 0, 0])}
    b = {"id": 2, "t": 101.0, "emb": _n([0, 1, 0])}
    m = series.group_series([a, b], 10, 0.88, 0.92)
    assert m[1] != m[2]


def test_no_timestamp_merges_on_tight_embed():
    a = {"id": 1, "t": None, "emb": _n([1, 0, 0])}
    b = {"id": 2, "t": None, "emb": _n([1, 0, 0.01])}
    m = series.group_series([a, b], 10, 0.88, 0.92)
    assert m[1] == m[2]


def test_three_frame_burst_one_group():
    items = [
        {"id": 1, "t": 10.0, "emb": _n([1, 0, 0])},
        {"id": 2, "t": 11.0, "emb": _n([0.99, 0.05, 0])},
        {"id": 3, "t": 12.0, "emb": _n([0.98, 0.07, 0])},
    ]
    m = series.group_series(items, 10, 0.88, 0.92)
    assert m[1] == m[2] == m[3]


def test_empty():
    assert series.group_series([], 10, 0.88, 0.92) == {}
