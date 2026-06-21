"""Pure-math quality signals. numpy-only — no models, no cv2. Fully unit-testable."""

import numpy as np

from . import config


# ---------------------------------------------------------------- sharpness
def laplacian_var(gray):
    """Variance of a 3x3 Laplacian. Higher = sharper. numpy-only convolution."""
    g = np.asarray(gray, dtype=np.float64)
    if g.ndim != 2 or g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4.0 * g[1:-1, 1:-1]
    return float(lap.var())


def norm_sharpness(var):
    return float(np.clip(var / config.SHARPNESS_CAP, 0.0, 1.0))


def squash_sharpness(var):
    """Monotone 1 - exp(-var/k). Unlike the hard cap, this keeps discriminating at
    the high end (every in-focus photo no longer saturates to 1.0)."""
    return float(1.0 - np.exp(-max(0.0, var) / config.SHARPNESS_SQUASH_K))


def colorfulness(rgb):
    """Hasler–Süsstrunk colorfulness, normalized to ~[0,1]."""
    a = np.asarray(rgb, dtype=np.float64)
    if a.ndim != 3 or a.shape[2] < 3:
        return 0.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    rg, yb = r - g, 0.5 * (r + g) - b
    val = np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    return float(np.clip(val / 100.0, 0.0, 1.0))


def aesthetic_proxy(rgb, sharp, exposure):
    """Heuristic aesthetic score [0,1] from colorfulness + exposure + sharpness.
    A defensible proxy, NOT a learned aesthetic model — swap in a trained head later."""
    c = colorfulness(rgb) if rgb is not None else 0.4
    score = config.AESTHETIC_W_COLOR * c + config.AESTHETIC_W_EXPOSURE * exposure + config.AESTHETIC_W_SHARP * sharp
    return float(np.clip(score, 0.0, 1.0))


# ---------------------------------------------------------------- exposure
def exposure_score(gray):
    """Peak at mean=128; subtract a penalty for clipped shadows/highlights. [0,1]."""
    g = np.asarray(gray, dtype=np.float64)
    if g.size == 0:
        return 0.0
    base = 1.0 - abs(g.mean() - 128.0) / 128.0
    clip_lo = float((g <= 4).sum()) / g.size
    clip_hi = float((g >= 251).sum()) / g.size
    return float(np.clip(base - (clip_lo + clip_hi), 0.0, 1.0))


# ---------------------------------------------------------------- eyes
def ear(pts):
    """Eye Aspect Ratio from 6 points [p1..p6] (corners + 2 upper + 2 lower lids)."""
    p = np.asarray(pts, dtype=np.float64)
    a = np.linalg.norm(p[1] - p[5])
    b = np.linalg.norm(p[2] - p[4])
    c = np.linalg.norm(p[0] - p[3])
    return float((a + b) / (2.0 * c + 1e-6))


def eye_openness(ear_left, ear_right):
    """Map worst-eye EAR (~0.10 closed .. ~0.30 open) to [0,1]. min => one shut eye penalized."""
    e = min(ear_left, ear_right)
    return float(np.clip((e - 0.10) / (0.30 - 0.10), 0.0, 1.0))


# ---------------------------------------------------------------- pose / expression
def frontality(left_eye, right_eye, nose):
    """1.0 = nose centered between eyes (straight-on); lower for profiles."""
    le = np.asarray(left_eye, dtype=np.float64)
    re = np.asarray(right_eye, dtype=np.float64)
    no = np.asarray(nose, dtype=np.float64)
    mid_x = (le[0] + re[0]) / 2.0
    eye_dist = np.linalg.norm(re - le)
    offset = abs(no[0] - mid_x) / (eye_dist + 1e-6)
    return float(np.clip(1.0 - offset * 2.0, 0.0, 1.0))


def smile(mouth_left, mouth_right, lip_top, lip_bottom):
    """Mouth open-height / width ratio -> [0,1]. Mild positive signal."""
    ml = np.asarray(mouth_left, dtype=np.float64)
    mr = np.asarray(mouth_right, dtype=np.float64)
    w = np.linalg.norm(mr - ml)
    h = abs(float(lip_bottom[1]) - float(lip_top[1]))
    return float(np.clip((h / (w + 1e-6)) * 2.5, 0.0, 1.0))


# --------------------------------------------- P1: MediaPipe blendshapes + head pose
# Richer, more robust signals than the bare mesh geometry above. All pure math over
# values the score phase reads from one FaceLandmarker pass (blendshape scores in
# [0,1]; a 4x4 facial-transformation matrix). Each degrades to the geometry signals
# when blendshapes/the transform are unavailable.
def euler_from_matrix(matrix):
    """(yaw, pitch, roll) in degrees from a face transform matrix (rotation in the
    upper-left 3x3). yaw = head turn L/R, pitch = nod up/down, roll = tilt. Standard
    ZYX decomposition; sign conventions may vary, so frontality uses magnitudes only."""
    m = np.asarray(matrix, dtype=np.float64)
    r = m[:3, :3]
    sy = float(np.hypot(r[0, 0], r[1, 0]))
    if sy > 1e-6:
        pitch = np.degrees(np.arctan2(r[2, 1], r[2, 2]))
        yaw = np.degrees(np.arctan2(-r[2, 0], sy))
        roll = np.degrees(np.arctan2(r[1, 0], r[0, 0]))
    else:  # gimbal lock
        pitch = np.degrees(np.arctan2(-r[1, 2], r[1, 1]))
        yaw = np.degrees(np.arctan2(-r[2, 0], sy))
        roll = 0.0
    return float(yaw), float(pitch), float(roll)


def pose_frontality(yaw, pitch, roll):
    """1.0 = head facing the lens; falls off with combined yaw+pitch deviation. Roll
    (tilt) does NOT reduce facing — a tilted head still looks at the camera. [0,1]."""
    dev = float(np.hypot(yaw, pitch))  # symmetric in yaw/pitch -> sign/axis-swap robust
    return float(np.clip(1.0 - dev / config.POSE_FRONTAL_FALLOFF, 0.0, 1.0))


def eye_open_from_blink(blink_left, blink_right):
    """Combined eye openness from the eyeBlink blendshapes (0=open .. 1=closed). Worst
    eye drives it (one shut eye is penalized), matching the EAR-min convention. [0,1]."""
    ol = 1.0 - float(np.clip(blink_left, 0.0, 1.0))
    orr = 1.0 - float(np.clip(blink_right, 0.0, 1.0))
    return float(min(ol, orr))


def gaze_at_camera(look_offsets):
    """Looking-at-lens score from the eyeLook* blendshapes (in/out/up/down per eye,
    each 0..1). All near 0 => eyes on the lens; a strong look-away -> ~0. None if no
    values."""
    vals = [abs(float(x)) for x in look_offsets if x is not None]
    if not vals:
        return None
    drive = sum(vals) / len(vals)
    return float(np.clip(1.0 - drive / config.GAZE_AWAY_FALLOFF, 0.0, 1.0))


def genuine_smile(smile_left, smile_right, cheek_left, cheek_right):
    """Duchenne (genuine) smile [0,1]: mouth smile gated by cheek-raise (eye crinkle).
    A mouth-only 'say cheese' scores lower than a cheek-co-activated real smile."""
    sm = 0.5 * (float(np.clip(smile_left, 0.0, 1.0)) + float(np.clip(smile_right, 0.0, 1.0)))
    ch = 0.5 * (float(np.clip(cheek_left, 0.0, 1.0)) + float(np.clip(cheek_right, 0.0, 1.0)))
    return float(np.clip(sm * (config.DUCHENNE_BASE + (1.0 - config.DUCHENNE_BASE) * ch), 0.0, 1.0))


# ------------------------------------------------- P1: light / color / focus signals
# All pure numpy over already-stored pixels (the image thumbnail, the per-face thumbs,
# and the raw sharpness values) — no originals re-read, no new model. Each is a plain
# scalar the score phase stores; the inspector surfaces the bad ones as flags.
def highlight_frac(gray):
    """Fraction of near-white (blown) pixels. gray in [0,255]."""
    g = np.asarray(gray, dtype=np.float64)
    return float((g >= 250).mean()) if g.size else 0.0


def shadow_frac(gray):
    """Fraction of crushed-black pixels."""
    g = np.asarray(gray, dtype=np.float64)
    return float((g <= 4).mean()) if g.size else 0.0


def global_contrast(gray):
    """Tonal spread = std of luminance, normalized. Low = flat/hazy. [0,1]."""
    g = np.asarray(gray, dtype=np.float64)
    return float(np.clip(g.std() / 128.0, 0.0, 1.0)) if g.size else 0.0


def color_cast(rgb):
    """Residual white-balance cast [0,1] (0 = neutral). Measured ONLY on low-saturation
    mid-luma pixels — the ones that *should* be gray — so a deliberately warm/golden
    frame (saturated warmth) doesn't false-flag; only a tint on the neutrals counts."""
    a = np.asarray(rgb, dtype=np.float64)
    if a.ndim != 3 or a.shape[2] < 3 or a.size == 0:
        return 0.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    neutral = ((a.max(-1) - a.min(-1)) < 25) & (luma > 60) & (luma < 200)
    if int(neutral.sum()) < 20:
        return 0.0
    rg = float((r[neutral] - g[neutral]).mean())
    yb = float((0.5 * (r[neutral] + g[neutral]) - b[neutral]).mean())
    return float(np.clip(np.hypot(rg, yb) / config.CAST_FALLOFF, 0.0, 1.0))


def hue_variance(rgb):
    """Circular variance of hue over colorful pixels [0,1]. Low = coherent palette,
    high = scattered. Tempers raw colorfulness so a garish frame isn't over-rewarded."""
    a = np.asarray(rgb, dtype=np.float64) / 255.0
    if a.ndim != 3 or a.shape[2] < 3 or a.size == 0:
        return 0.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    chroma = a.max(-1) - a.min(-1)
    mask = chroma > 0.15  # enough saturation for a meaningful hue
    if int(mask.sum()) < 10:
        return 0.0
    alpha = 0.5 * (2 * r - g - b)
    beta = (np.sqrt(3.0) / 2.0) * (g - b)
    hue = np.arctan2(beta, alpha)[mask]
    resultant = float(np.hypot(np.cos(hue).mean(), np.sin(hue).mean()))
    return float(np.clip(1.0 - resultant, 0.0, 1.0))


def skin_exposure_agg(face_exposures):
    """Subject (skin-tone) exposure: worst-blended mean of per-face exposure scores.
    None if no faces. An underexposed subject reads low even when global exposure is
    fine (backlit/spotlit scenes)."""
    v = [x for x in face_exposures if x is not None]
    if not v:
        return None
    return float(0.5 * min(v) + 0.5 * (sum(v) / len(v)))


def bokeh_ratio(face_sharp_raw, bg_sharp_raw):
    """Subject-vs-background sharpness [0,1]: high when the face is sharp and the
    background soft (intentional bokeh / good focus), ~0.5 when equal, low on a focus
    miss. None if either input is missing."""
    if face_sharp_raw is None or bg_sharp_raw is None:
        return None
    f = max(0.0, float(face_sharp_raw))
    b = max(0.0, float(bg_sharp_raw))
    return float(f / (f + b + 1e-6))


def area_weighted_sharpness(sharps, areas):
    """Area-weighted mean of per-face sharpness so a tiny background face can't drag
    the group sharpness aggregate. None if no faces."""
    s = [float(x) if x is not None else 0.0 for x in sharps]
    if not s:
        return None
    w = area_weights(areas)
    return float(np.dot(np.asarray(s, dtype=np.float64), w)) if len(w) else float(np.mean(s))


def horizon_tilt(gray):
    """Dutch-tilt [0,1] (0 = level). Weighted dominant strong-edge orientation, but
    GATED: returns 0 when no single axis dominates (busy scene), so it never invents a
    tilt. Operates on the downscaled gray thumbnail."""
    g = np.asarray(gray, dtype=np.float64)
    if g.ndim != 2 or min(g.shape) < 16:
        return 0.0
    gy = g[2:, 1:-1] - g[:-2, 1:-1]
    gx = g[1:-1, 2:] - g[1:-1, :-2]
    mag = np.hypot(gx, gy)
    m = mag > (mag.mean() + mag.std())  # strong edges only
    if int(m.sum()) < 32:
        return 0.0
    edge = (np.degrees(np.arctan2(gy[m], gx[m])) + 90.0) % 180.0  # edge orientation
    w = mag[m]
    rad2 = np.radians(2.0 * edge)  # double-angle: axial (0≡180) averaging
    cc = float(np.average(np.cos(rad2), weights=w))
    ss = float(np.average(np.sin(rad2), weights=w))
    if np.hypot(cc, ss) < config.HORIZON_MIN_CONC:  # no dominant axis -> unknown
        return 0.0
    dom = (np.degrees(np.arctan2(ss, cc)) / 2.0) % 90.0  # dominant orientation mod 90
    dev = min(dom, 90.0 - dom)  # distance to nearest level/plumb axis
    return float(np.clip(dev / config.HORIZON_MAX_TILT_DEG, 0.0, 1.0))


def kps_plausible(kps, box):
    """Anatomical sanity on the detector's 5 keypoints [left_eye, right_eye, nose,
    mouth_left, mouth_right] (image coords). Rejects the collapsed/impossible
    geometry typical of hair/fabric/back-of-head false positives. Cheap, no model."""
    k = np.asarray(kps, dtype=np.float64)
    if k.shape[0] < 5:
        return False
    le, re, nose, ml, mr = k[0], k[1], k[2], k[3], k[4]
    x1, y1, x2, y2 = box
    w, h = max(x2 - x1, 1.0), max(y2 - y1, 1.0)
    for p in k:  # all keypoints near/inside the box
        if not (x1 - 0.2 * w <= p[0] <= x2 + 0.2 * w and y1 - 0.2 * h <= p[1] <= y2 + 0.2 * h):
            return False
    if le[0] >= re[0]:  # left eye left of right eye
        return False
    eye_y, mouth_y, tol = (le[1] + re[1]) / 2.0, (ml[1] + mr[1]) / 2.0, 0.1 * h
    return eye_y < nose[1] + tol and nose[1] < mouth_y + tol and eye_y < mouth_y


# ---------------------------------------------------------------- composites
def face_quality(sharp, bright, eye, frontal, sm):
    """Best-face-of-a-person score. All inputs in [0,1]."""
    return float(
        config.FACE_W_SHARP * sharp
        + config.FACE_W_BRIGHT * bright
        + config.FACE_W_EYE * eye
        + config.FACE_W_FRONTAL * frontal
        + config.FACE_W_SMILE * sm
    )


def _eyes_aggregate(eyes_list):
    """(legacy helper, kept for reference/tests) Face-count-aware eye aggregate."""
    n = len(eyes_list)
    if n == 0:
        return 0.5
    if n == 1:
        return eyes_list[0]
    if n <= 3:
        return 0.5 * min(eyes_list) + 0.5 * (sum(eyes_list) / n)
    return min(eyes_list)


# ---------------------------------------------------------------- per-image metrics
# Every per-image criterion is computed from the same per-face inputs. `faces` is a
# list of {"eye","smile","front","area"} (eye/smile/front in [0,1]; area in px²). The
# SAME signals feed every pick; only the WEIGHTING differs, so context decides — a
# group photo keeps eyes strict, a moment lets a great frame beat a blink.
def face_area(bbox):
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def area_weights(areas):
    """sqrt-area weights, normalized — a tiny background face can't dominate a foreground one."""
    a = np.sqrt(np.clip(np.asarray(areas, dtype=np.float64), 0.0, None))
    s = float(a.sum())
    if s <= 0.0:
        n = len(areas)
        return np.full(n, 1.0 / n) if n else np.zeros(0)
    return a / s


def fraction_at_least(values, thr):
    """Fraction of faces meeting a threshold (the plain-language 'everyone' tags). None if no faces."""
    v = [x for x in values if x is not None]
    if not v:
        return None
    return float(sum(1 for x in v if x >= thr) / len(v))


def blur_floor(global_sharp):
    """Continuous [PRINT_BLUR_PENALTY .. 1] multiplier replacing the old ×0.25 step
    cliff: heavy when very soft, ~1 when sharp, smooth through the disqualify point —
    so a frame at 0.149 isn't slammed while 0.151 sails through."""
    x = (float(global_sharp) - config.PRINT_DISQUALIFY_SHARP) / max(config.BLUR_FLOOR_WIDTH, 1e-6)
    s = 1.0 / (1.0 + np.exp(-x))
    return float(config.PRINT_BLUR_PENALTY + (1.0 - config.PRINT_BLUR_PENALTY) * s)


def _faces_arrays(faces):
    eyes = [f.get("eye", 0.5) for f in faces]
    smiles = [f.get("smile", 0.0) for f in faces]
    fronts = [f.get("front", 0.0) for f in faces]
    areas = [f.get("area", 1.0) for f in faces]
    return eyes, smiles, fronts, areas


def group_eyes(faces):
    """Eyes-strict aggregate for the GROUP pick: area-weighted mean blended with the
    WORST eye, so a foreground blink really hurts but a tiny background blink doesn't
    zero the frame. (For a group photo, eyes matter most.)"""
    if not faces:
        return 0.5
    eyes, _, _, areas = _faces_arrays(faces)
    w = area_weights(areas)
    wmean = float(np.dot(np.asarray(eyes, float), w)) if len(w) else float(np.mean(eyes))
    return config.GROUP_EYES_WMEAN * wmean + config.GROUP_EYES_MIN * float(min(eyes))


def _stragglers(faces):
    return sum(
        1
        for f in faces
        if f.get("eye", 1.0) < config.EYE_OPEN_THR
        or f.get("smile", 1.0) < config.SMILE_THR
        or f.get("front", 1.0) < config.FRONT_THR
    )


def print_score(global_sharp, exposure, faces):
    """The GROUP criterion. Eyes stay important: eyes-strict aggregate + a per-straggler
    penalty + fraction-based expression so one frowner among many is visible. Continuous
    blur floor. `faces`: list of {eye,smile,front,area}. [0,1]."""
    if faces:
        eyes_term = group_eyes(faces)
        _, smiles, fronts, _ = _faces_arrays(faces)
        fs = fraction_at_least(smiles, config.SMILE_THR) or 1.0
        ff = fraction_at_least(fronts, config.FRONT_THR) or 1.0
        expr = 0.5 * fs + 0.5 * ff
        strag = min(_stragglers(faces), config.STRAGGLER_CAP) * config.STRAGGLER_PEN
    else:
        eyes_term, expr, strag = 0.5, 0.5, 0.0
    score = (
        config.PRINT_W_SHARP * global_sharp
        + config.PRINT_W_EXPOSURE * exposure
        + config.PRINT_W_EYES * eyes_term
        + config.PRINT_W_EXPR * expr
        - strag
    )
    return float(np.clip(score * blur_floor(global_sharp), 0.0, 1.0))


def moment_score(global_sharp, exposure, faces):
    """The MOMENT criterion — a great frame beats a blink. Eyes are a SOFT mean, never
    a gate; the strongest smile carries the frame; sharpness still matters. [0,1]."""
    if faces:
        eyes, smiles, fronts, _ = _faces_arrays(faces)
        joy = max(smiles) if smiles else 0.0
        eng = float(np.mean([0.5 * e + 0.5 * fr for e, fr in zip(eyes, fronts, strict=True)]))
    else:
        joy, eng = 0.0, 0.5
    score = (
        config.MOMENT_W_JOY * joy
        + config.MOMENT_W_ENGAGE * eng
        + config.MOMENT_W_SHARP * global_sharp
        + config.MOMENT_W_EXPO * exposure
    )
    return float(np.clip(score * blur_floor(global_sharp), 0.0, 1.0))


def cohesion_score(faces):
    """'Everyone engaged' (the EVERYONE pick): fraction of faces simultaneously
    eyes-open / smiling / facing, blended with the mean engagement. [0,1]."""
    if not faces:
        return 0.5
    eyes, smiles, fronts, _ = _faces_arrays(faces)
    frac = (
        (fraction_at_least(eyes, config.EYE_OPEN_THR) or 0.0)
        + (fraction_at_least(smiles, config.SMILE_THR) or 0.0)
        + (fraction_at_least(fronts, config.FRONT_THR) or 0.0)
    ) / 3.0
    mean_eng = float(np.mean([e * (0.5 + 0.5 * fr) for e, fr in zip(eyes, fronts, strict=True)]))
    return float(np.clip(0.6 * frac + 0.4 * mean_eng, 0.0, 1.0))


def joy_score(faces):
    """Biggest smile in the frame (the SMILE pick)."""
    if not faces:
        return 0.0
    _, smiles, _, _ = _faces_arrays(faces)
    return float(max(smiles) if smiles else 0.0)


def candid_score(global_sharp, exposure, faces):
    """The CANDID criterion: natural/un-posed — present smile + off-axis gaze, SOFT on
    eyes, still technically usable. [0,1]."""
    if not faces:
        return 0.0
    _, smiles, fronts, _ = _faces_arrays(faces)
    sm = sum(smiles) / len(smiles)
    off = 1.0 - (sum(fronts) / len(fronts))  # off-axis = candid
    score = 0.35 * global_sharp + 0.15 * exposure + 0.30 * sm + 0.20 * off
    return float(np.clip(score * blur_floor(global_sharp), 0.0, 1.0))


def composition_score(bboxes, width, height):
    """Crop-safety (no face sliced at the edge) + rule-of-thirds (area-weighted subject
    centroid) + headroom, from face bboxes (original px). No faces -> neutral. [0,1]."""
    if not bboxes or not width or not height:
        return 0.5
    W, H = float(width), float(height)
    m = 0.01
    pen = sum(
        config.CROP_EDGE_PEN
        for (x1, y1, x2, y2) in bboxes
        if x1 <= m * W or y1 <= m * H or x2 >= (1.0 - m) * W or y2 >= (1.0 - m) * H
    )
    crop = max(0.0, 1.0 - min(pen, 1.0))
    w = area_weights([face_area(b) for b in bboxes])
    cx = sum(w[i] * ((bboxes[i][0] + bboxes[i][2]) / 2.0 / W) for i in range(len(bboxes)))
    cy = sum(w[i] * ((bboxes[i][1] + bboxes[i][3]) / 2.0 / H) for i in range(len(bboxes)))
    d = min(((cx - px) ** 2 + (cy - py) ** 2) ** 0.5 for px in (1 / 3, 2 / 3) for py in (1 / 3, 2 / 3))
    thirds = float(np.clip(1.0 - d / 0.393, 0.0, 1.0))  # center -> nearest third ≈ 0.393
    top = min(b[1] for b in bboxes) / H
    headroom = float(np.clip(1.0 - abs(top - 0.12) / 0.25, 0.0, 1.0))
    return float(np.clip(0.45 * crop + 0.35 * thirds + 0.20 * headroom, 0.0, 1.0))
