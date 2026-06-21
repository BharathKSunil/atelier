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
    assert quality.blur_floor(0.02) > 0.0 and quality.blur_floor(0.9) <= 1.0


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


# ---------------------------------------------------------------- P1 signals
def test_euler_identity_is_frontal():
    yaw, pitch, roll = quality.euler_from_matrix(np.eye(4))
    assert abs(yaw) < 1e-6 and abs(pitch) < 1e-6 and abs(roll) < 1e-6
    assert quality.pose_frontality(yaw, pitch, roll) == 1.0


def test_euler_yaw_recovered():
    # 30° rotation about the vertical (Y) axis -> yaw magnitude ~30
    t = np.radians(30.0)
    r = np.array([[np.cos(t), 0, np.sin(t)], [0, 1, 0], [-np.sin(t), 0, np.cos(t)]])
    m = np.eye(4)
    m[:3, :3] = r
    yaw, pitch, roll = quality.euler_from_matrix(m)
    assert abs(abs(yaw) - 30.0) < 1e-3


def test_pose_frontality_falls_off_and_roll_blind():
    assert quality.pose_frontality(0, 0, 0) == 1.0
    assert quality.pose_frontality(45, 0, 0) == 0.0  # at the falloff
    assert quality.pose_frontality(0, 0, 40) == 1.0  # pure tilt still faces the lens
    assert quality.pose_frontality(20, 0, 0) > quality.pose_frontality(35, 0, 0)


def test_eye_open_from_blink_worst_eye():
    assert quality.eye_open_from_blink(0.0, 0.0) == 1.0  # both wide open
    assert quality.eye_open_from_blink(0.0, 1.0) == 0.0  # one shut -> penalized
    assert quality.eye_open_from_blink(0.2, 0.1) == 0.8  # worst eye drives it


def test_gaze_at_camera():
    assert quality.gaze_at_camera([0, 0, 0, 0]) == 1.0  # eyes on the lens
    assert quality.gaze_at_camera([0.6, 0.6, 0.6, 0.6]) == 0.0  # hard look-away
    assert quality.gaze_at_camera([None, None]) is None  # no data
    assert quality.gaze_at_camera([0.1, 0.0, 0.1, 0.0]) > quality.gaze_at_camera([0.5, 0.4, 0.3, 0.2])


def test_genuine_smile_rewards_cheek_raise():
    forced = quality.genuine_smile(0.9, 0.9, 0.0, 0.0)  # mouth only
    real = quality.genuine_smile(0.9, 0.9, 0.9, 0.9)  # mouth + cheek crinkle
    assert real > forced
    assert quality.genuine_smile(0.0, 0.0, 0.9, 0.9) == 0.0  # no mouth smile -> not a smile
    assert 0.0 <= forced <= 1.0 and 0.0 <= real <= 1.0


# ---------------------------------------------------------------- P1 light/colour/focus
def test_highlight_and_shadow_frac():
    assert quality.highlight_frac(np.full((8, 8), 255, np.uint8)) == 1.0
    assert quality.highlight_frac(np.full((8, 8), 128, np.uint8)) == 0.0
    assert quality.shadow_frac(np.zeros((8, 8), np.uint8)) == 1.0
    assert quality.shadow_frac(np.full((8, 8), 128, np.uint8)) == 0.0


def test_global_contrast():
    flat = quality.global_contrast(np.full((8, 8), 128, np.uint8))
    cb = np.indices((8, 8)).sum(0) % 2 * 255
    assert flat == 0.0
    assert quality.global_contrast(cb.astype(np.uint8)) > flat


def test_color_cast_only_on_neutrals():
    gray = np.full((8, 8, 3), 128, np.uint8)
    cast = gray.copy()
    cast[..., 1] = 150  # the *neutral* pixels tinted green = a white-balance cast
    saturated = gray.copy()
    saturated[..., 1] = 230  # a vivid green (high-sat) is NOT a cast -> ignored
    assert quality.color_cast(gray) == 0.0
    assert quality.color_cast(cast) > 0.2
    assert quality.color_cast(saturated) == 0.0  # saturated colour is not a WB error


def test_hue_variance_single_vs_mixed():
    one = np.zeros((16, 16, 3), np.uint8)
    one[..., 0] = 220  # all red
    mixed = np.random.default_rng(1).integers(0, 255, (16, 16, 3), dtype=np.uint8)
    assert quality.hue_variance(one) < quality.hue_variance(mixed)
    assert quality.hue_variance(np.full((8, 8, 3), 128, np.uint8)) == 0.0  # gray -> no hue


def test_skin_exposure_agg():
    assert quality.skin_exposure_agg([]) is None
    assert quality.skin_exposure_agg([None]) is None
    one_dim = quality.skin_exposure_agg([0.9, 0.2])  # a dim face drags it
    assert one_dim < 0.9


def test_bokeh_ratio():
    assert quality.bokeh_ratio(None, 100) is None
    assert abs(quality.bokeh_ratio(300, 300) - 0.5) < 1e-3  # equal -> mid
    assert quality.bokeh_ratio(900, 100) > 0.8  # sharp subject, soft bg
    assert quality.bokeh_ratio(100, 900) < 0.2  # focus missed


def test_area_weighted_sharpness_ignores_tiny_face():
    # big sharp face + tiny soft face -> aggregate stays high
    agg = quality.area_weighted_sharpness([0.9, 0.1], [40000.0, 100.0])
    assert agg > 0.8
    assert quality.area_weighted_sharpness([], []) is None


def _tilted_edge(deg, n=64):
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    t = np.radians(deg)
    return ((np.sin(t) * xx - np.cos(t) * yy > 0) * 255).astype(np.uint8)


def test_horizon_tilt_level_vs_tilted_and_gated():
    assert quality.horizon_tilt(_tilted_edge(0)) < 0.2  # horizontal -> level
    assert quality.horizon_tilt(_tilted_edge(90)) < 0.2  # vertical -> level
    assert quality.horizon_tilt(_tilted_edge(8)) > quality.horizon_tilt(_tilted_edge(0))
    busy = np.random.default_rng(2).integers(0, 255, (64, 64), dtype=np.uint8)
    assert quality.horizon_tilt(busy) == 0.0  # no dominant axis -> gated to 0


# ---------------------------------------------------------------- P2/P3 scene/focus/dup
def test_warmth_warm_vs_cool():
    warm = np.zeros((8, 8, 3), np.uint8)
    warm[..., 0] = 220
    warm[..., 2] = 40
    cool = np.zeros((8, 8, 3), np.uint8)
    cool[..., 0] = 40
    cool[..., 2] = 220
    neutral = np.full((8, 8, 3), 128, np.uint8)
    assert quality.warmth(warm) > quality.warmth(neutral) > quality.warmth(cool)
    assert abs(quality.warmth(neutral) - 0.5) < 0.05


def test_clutter_excludes_faces():
    flat = np.full((32, 32), 128, np.uint8)
    busy = np.random.default_rng(5).integers(0, 255, (32, 32), dtype=np.uint8)  # high-freq texture
    assert quality.clutter(flat, []) == 0.0
    assert quality.clutter(busy, []) > 0.3
    assert quality.clutter(busy, [(0, 0, 32, 32)]) == 0.0  # all bg masked out


def test_symmetry_mirror_vs_ramp():
    base = np.arange(8)
    row = np.concatenate([base, base[::-1]]).astype(np.uint8)  # mirror-symmetric row
    sym = np.tile(row, (16, 1))
    ramp = np.tile(np.arange(16), (16, 1)).astype(np.uint8)
    assert quality.symmetry(sym) > 0.95
    assert quality.symmetry(ramp) < quality.symmetry(sym)


def test_rim_light_backlit():
    g = np.full((40, 40), 200, np.uint8)  # bright surround
    g[10:30, 10:30] = 40  # dark subject
    assert quality.rim_light(g, (10, 10, 30, 30)) > 0.2
    assert quality.rim_light(np.full((40, 40), 128, np.uint8), (10, 10, 30, 30)) == 0.0
    assert quality.rim_light(g, None) == 0.0


def test_motion_blur_directional_vs_isotropic():
    directional = np.tile(np.linspace(0, 255, 32).reshape(32, 1), (1, 32)).astype(np.uint8)
    iso = np.random.default_rng(3).integers(0, 255, (32, 32), dtype=np.uint8)
    assert quality.motion_blur(directional) > quality.motion_blur(iso)
    assert quality.motion_blur(directional) > 0.5


def test_grimace_and_talking():
    assert quality.grimace(0.1, 0.7, 0.2) == 0.7  # strongest transient
    assert quality.mouth_open_talking(0.8, 0.1) > quality.mouth_open_talking(0.8, 0.9)  # a smile suppresses talking
    assert quality.mouth_open_talking(0.0, 0.0) == 0.0


def test_cosine_and_redundancy():
    a, b, c = np.array([1.0, 0, 0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    assert abs(quality.cosine_sim(a, b) - 1.0) < 1e-9
    assert abs(quality.cosine_sim(a, c)) < 1e-9
    assert quality.max_redundancy(a, [c, b]) > 0.99  # a near-dup is present
    assert quality.max_redundancy(a, []) is None
