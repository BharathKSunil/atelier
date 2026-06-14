"""Centroid-merge post-pass: vectorized cosine merge must collapse near-identical
clusters, keep distant ones apart, and preserve noise."""
import numpy as np

from atelier.pipeline.cluster import _merge_by_centroid


def test_merge_close_keep_far_preserve_noise():
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    a2 = np.array([0.98, 0.02, 0.0], dtype=np.float32)   # ~identical direction to a
    b = np.array([0.0, 1.0, 0.0], dtype=np.float32)      # orthogonal
    X = np.stack([a, a, a2, a2, b, b])
    labels = np.array([0, 0, 1, 1, 2, -1])               # last point is noise
    out = _merge_by_centroid(X, labels, 0.9)
    assert out[0] == out[2]        # clusters 0 and 1 merged (cos ~1.0)
    assert out[0] != out[4]        # cluster 2 stays separate (cos ~0)
    assert out[5] == -1            # noise preserved


def test_single_cluster_is_noop():
    X = np.eye(3, dtype=np.float32)[[0, 0, 0]]
    labels = np.array([0, 0, 0])
    assert list(_merge_by_centroid(X, labels, 0.9)) == [0, 0, 0]
