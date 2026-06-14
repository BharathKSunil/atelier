import numpy as np

from facelib import quality


def test_laplacian_flat_is_zero():
    assert quality.laplacian_var(np.full((10, 10), 128, np.uint8)) == 0.0


def test_laplacian_edge_positive():
    g = np.zeros((10, 10), np.uint8)
    g[:, 5:] = 255
    assert quality.laplacian_var(g) > 0


def test_laplacian_tiny_crop_safe():
    assert quality.laplacian_var(np.zeros((2, 2), np.uint8)) == 0.0


def test_exposure_mid_beats_dark():
    mid = np.full((20, 20), 128, np.uint8)
    dark = np.zeros((20, 20), np.uint8)
    assert quality.exposure_score(mid) > quality.exposure_score(dark)


def test_exposure_penalizes_clipping():
    assert quality.exposure_score(np.full((20, 20), 255, np.uint8)) < 0.5


def test_eye_open_vs_closed():
    open_pts = np.array([[0, 0], [1, 2], [2, 2], [3, 0], [2, -2], [1, -2]], float)
    closed_pts = np.array([[0, 0], [1, .2], [2, .2], [3, 0], [2, -.2], [1, -.2]], float)
    eo = quality.eye_openness(quality.ear(open_pts), quality.ear(open_pts))
    ec = quality.eye_openness(quality.ear(closed_pts), quality.ear(closed_pts))
    assert eo > ec


def test_frontality_centered_is_high():
    front = quality.frontality([0, 0], [10, 0], [5, 3])     # nose centered
    profile = quality.frontality([0, 0], [10, 0], [9, 3])   # nose near one eye
    assert front > profile
    assert front > 0.9


def test_print_score_min_eyes_dominates():
    all_open = quality.print_score(0.8, 0.8, [0.9, 0.9], [0.8, 0.8])
    one_blink = quality.print_score(0.8, 0.8, [0.9, 0.05], [0.8, 0.8])
    assert all_open > one_blink


def test_print_score_blur_disqualified():
    sharp = quality.print_score(0.8, 0.8, [0.9], [0.8])
    blur = quality.print_score(0.05, 0.8, [0.9], [0.8])
    assert blur < sharp * 0.6


def test_print_score_no_faces_uses_defaults():
    s = quality.print_score(0.8, 0.8, [], [])
    assert 0.0 <= s <= 1.0


def test_face_quality_monotonic_in_sharpness():
    lo = quality.face_quality(0.1, 0.5, 0.5, 0.5, 0.5)
    hi = quality.face_quality(0.9, 0.5, 0.5, 0.5, 0.5)
    assert hi > lo


def test_squash_sharpness_monotone_unsaturated():
    a = quality.squash_sharpness(150)
    b = quality.squash_sharpness(600)
    assert 0 < a < b < 1.0           # keeps discriminating past the old cap


def test_eyes_aggregate_single_vs_group():
    # one closed eye: lone subject uses mean (forgiving), big group uses min (strict)
    assert quality._eyes_aggregate([0.1]) == 0.1
    assert quality._eyes_aggregate([0.9, 0.9, 0.9, 0.1]) == 0.1
    blend = quality._eyes_aggregate([0.9, 0.1])
    assert 0.1 < blend < 0.9


def test_colorfulness_gray_is_zero():
    gray = np.full((20, 20, 3), 128, np.uint8)
    colorful = np.zeros((20, 20, 3), np.uint8)
    colorful[..., 0] = 230
    colorful[..., 2] = 20
    assert quality.colorfulness(gray) == 0.0
    assert quality.colorfulness(colorful) > 0.0


def test_aesthetic_proxy_in_range():
    rgb = np.random.default_rng(0).integers(0, 255, (16, 16, 3), dtype=np.uint8)
    s = quality.aesthetic_proxy(rgb, 0.7, 0.8)
    assert 0.0 <= s <= 1.0
    assert quality.aesthetic_proxy(None, 0.5, 0.5) >= 0.0   # missing image tolerated


def test_candid_prefers_offaxis_smile():
    posed = quality.candid_score(0.7, 0.8, [0.1], [0.95])     # smiling little, very frontal
    candid = quality.candid_score(0.7, 0.8, [0.8], [0.3])     # smiling, off-axis
    assert candid > posed
