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
    """Face-count-aware: a lone subject uses mean; a big group uses min (one blink
    ruins it); small groups blend. Avoids over-penalizing single-subject candids."""
    n = len(eyes_list)
    if n == 0:
        return 0.5
    if n == 1:
        return eyes_list[0]
    if n <= 3:
        return 0.5 * min(eyes_list) + 0.5 * (sum(eyes_list) / n)
    return min(eyes_list)


def print_score(global_sharp, exposure, eyes_list, expr_list):
    """Best-frame-to-print score (the 'group' criterion). Eyes aggregation adapts
    to face count. global_sharp, exposure image-level [0,1]; expr_list per-face
    (smile+frontality)/2."""
    eyes = _eyes_aggregate(eyes_list)
    expr = (sum(expr_list) / len(expr_list)) if expr_list else 0.5
    score = (
        config.PRINT_W_SHARP * global_sharp
        + config.PRINT_W_EXPOSURE * exposure
        + config.PRINT_W_EYES * eyes
        + config.PRINT_W_EXPR * expr
    )
    if global_sharp < config.PRINT_DISQUALIFY_SHARP:
        score *= config.PRINT_BLUR_PENALTY  # motion blur => not printable
    return float(score)


def candid_score(global_sharp, exposure, smile_list, frontality_list):
    """The 'candid' criterion: natural/un-posed — present smiles + off-axis gaze,
    while still technically usable (gated on sharpness/exposure). [0,1]."""
    if not smile_list:
        return 0.0
    sm = sum(smile_list) / len(smile_list)
    off = 1.0 - (sum(frontality_list) / len(frontality_list))  # off-axis = candid
    score = 0.35 * global_sharp + 0.15 * exposure + 0.30 * sm + 0.20 * off
    if global_sharp < config.PRINT_DISQUALIFY_SHARP:
        score *= config.PRINT_BLUR_PENALTY
    return float(max(0.0, min(1.0, score)))
