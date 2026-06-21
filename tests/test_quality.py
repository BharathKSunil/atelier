import numpy as np

from atelier import quality


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
    closed_pts = np.array([[0, 0], [1, 0.2], [2, 0.2], [3, 0], [2, -0.2], [1, -0.2]], float)
    eo = quality.eye_openness(quality.ear(open_pts), quality.ear(open_pts))
    ec = quality.eye_openness(quality.ear(closed_pts), quality.ear(closed_pts))
    assert eo > ec


def test_frontality_centered_is_high():
    front = quality.frontality([0, 0], [10, 0], [5, 3])  # nose centered
    profile = quality.frontality([0, 0], [10, 0], [9, 3])  # nose near one eye
    assert front > profile
    assert front > 0.9


def _f(eye, smile=0.5, front=0.8, area=10000.0):
    return {"eye": eye, "smile": smile, "front": front, "area": area}


def test_group_print_demotes_a_blink():
    # group photo: eyes still matter — a blink demotes the frame
    all_open = quality.print_score(0.8, 0.8, [_f(0.9), _f(0.9), _f(0.9), _f(0.9)])
    one_blink = quality.print_score(0.8, 0.8, [_f(0.9), _f(0.9), _f(0.9), _f(0.05)])
    assert all_open > one_blink


def test_print_score_no_faces_in_range():
    assert 0.0 <= quality.print_score(0.8, 0.8, []) <= 1.0


def test_blur_floor_is_continuous_not_a_cliff():
    a, b = quality.blur_floor(0.149), quality.blur_floor(0.151)
    assert abs(a - b) < 0.05  # no step at the old disqualify point
    assert quality.blur_floor(0.02) < quality.blur_floor(0.5)  # heavier when soft
    assert 0.0 < quality.blur_floor(0.02) and quality.blur_floor(0.9) <= 1.0


def test_print_score_blur_floor_demotes_soft():
    assert quality.print_score(0.05, 0.8, [_f(0.9)]) < quality.print_score(0.8, 0.8, [_f(0.9)])


def test_moment_beats_a_blink_where_group_does_not():
    """The product nuance: a sharp, joyful frame with one blink should WIN 'moment'
    over a stiff all-eyes-open frame — but LOSE 'group', where eyes matter."""
    joyful_blink = [_f(0.05, smile=0.95, front=0.6)]
    stiff_open = [_f(0.95, smile=0.10, front=0.95)]
    assert quality.moment_score(0.9, 0.8, joyful_blink) > quality.moment_score(0.9, 0.8, stiff_open)
    assert quality.print_score(0.9, 0.8, stiff_open) > quality.print_score(0.9, 0.8, joyful_blink)


def test_cohesion_rewards_everyone_engaged():
    everyone = [_f(0.9, 0.9, 0.9) for _ in range(4)]
    one_off = [_f(0.9, 0.9, 0.9), _f(0.9, 0.9, 0.9), _f(0.9, 0.9, 0.9), _f(0.1, 0.1, 0.1)]
    assert quality.cohesion_score(everyone) > quality.cohesion_score(one_off)


def test_joy_is_the_biggest_smile():
    assert quality.joy_score([_f(0.9, smile=0.2), _f(0.9, smile=0.8)]) == 0.8
    assert quality.joy_score([]) == 0.0


def test_fraction_at_least():
    assert quality.fraction_at_least([0.9, 0.9, 0.1, 0.1], 0.5) == 0.5
    assert quality.fraction_at_least([], 0.5) is None


def test_area_weights_favor_bigger_face():
    w = quality.area_weights([10000.0, 100.0])
    assert w[0] > w[1] and abs(float(w.sum()) - 1.0) < 1e-9


def test_composition_penalizes_edge_cut():
    centered = quality.composition_score([(400, 250, 600, 450)], 1000, 800)
    edge_cut = quality.composition_score([(0, 250, 200, 450)], 1000, 800)
    assert centered > edge_cut


def test_face_quality_monotonic_in_sharpness():
    lo = quality.face_quality(0.1, 0.5, 0.5, 0.5, 0.5)
    hi = quality.face_quality(0.9, 0.5, 0.5, 0.5, 0.5)
    assert hi > lo


def test_squash_sharpness_monotone_unsaturated():
    a = quality.squash_sharpness(150)
    b = quality.squash_sharpness(600)
    assert 0 < a < b < 1.0  # keeps discriminating past the old cap


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
    assert quality.aesthetic_proxy(None, 0.5, 0.5) >= 0.0  # missing image tolerated


def test_candid_prefers_offaxis_smile():
    posed = quality.candid_score(0.7, 0.8, [_f(0.9, smile=0.1, front=0.95)])  # smiling little, very frontal
    candid = quality.candid_score(0.7, 0.8, [_f(0.9, smile=0.8, front=0.3)])  # smiling, off-axis
    assert candid > posed
