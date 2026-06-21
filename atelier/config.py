"""Constants and tunables. No heavy imports — keep this dependency-free."""

import os
from pathlib import Path


def default_projects_dir():
    """Single source of truth for where projects live: ~/.atelier (override: $ATELIER_HOME)."""
    return os.environ.get("ATELIER_HOME") or str(Path.home() / ".atelier")


# insightface ONNX execution providers. None = auto-detect (CoreML on Apple Silicon
# -> ~2.7x detection / ~16x recognition here; CUDA on nvidia; else CPU).
INSIGHTFACE_PROVIDERS = None

# A run phase producing no output for this many seconds is treated as stalled
# (e.g. a hung model download) and terminated, so the UI fails instead of hanging.
RUN_PHASE_STALL_TIMEOUT_S = 1800

# --- Decode / sizing ---
ANALYSIS_LONG_EDGE = 1536  # downscale long edge for detection + global embedding
THUMB_MAX = 256  # stored face thumbnail max edge (px)
IMAGE_THUMB_MAX = 360  # stored per-image thumbnail max edge (px) — avoids re-decoding originals

# --- Face detection ---
# insightface: SCRFD/RetinaFace detector + ArcFace embeddings (buffalo_l) — far fewer
# false positives (jewelry/skin/blur) and far better clustering than the old MTCNN+FaceNet.
INSIGHTFACE_MODEL = "buffalo_l"
INSIGHTFACE_DET_SIZE = 640  # SCRFD standard; larger can MISS frame-filling faces

# Identity-embedding model (A/B switch). Detection always stays SCRFD (insightface);
# this only swaps what produces the 512-d embedding from the aligned 112x112 crop.
# "arcface"  = insightface buffalo_l ArcFace embedding (default, unchanged behavior).
# "adaface"  = mk-minchul AdaFace IR-101 / WebFace12M (quality-adaptive; better on
#              low-quality / varied-pose wedding faces). See atelier/recognition.py.
# A/B on a real 1798-img reception: AdaFace gave equal cluster count (~252 vs 251)
# and only +0.02 silhouette at ~25% slower — its edge is low-quality faces, which
# detection already gates out here. ArcFace (CoreML) stays default; flip for sets
# dominated by blurry/backlit faces, then re-index.
RECOGNITION_MODEL = "arcface"  # or "adaface"

# Quality gates applied at index time (reject non-faces before they ever cluster).
# Tuned from a measured score distribution: SCRFD false-positives on hair/fabric/
# backs-of-heads land at ~0.60-0.65, real faces at 0.80-0.99.
FACE_DET_THRESHOLD = 0.65  # min detector confidence (valley between junk and real faces)
FACE_DET_AUTO_ACCEPT = 0.80  # >= this -> trust SCRFD (skips the landmark gate, keeps profiles)
FACE_VERIFY_LANDMARKS = True  # for borderline faces, require MediaPipe to also find a face
# on the crop (hair/fabric have no eye/nose/mouth geometry)
FACE_MIN_PX = 32  # min bbox side in the analysis image (drops tiny background faces)
FACE_MIN_SHARPNESS = 0.12  # min squashed sharpness (drops out-of-focus blobs)
FACE_MIN_FRONTALITY = 0.35  # min frontality from detector keypoints (drops profiles/ears
# whose embeddings are unreliable and pollute clusters)

# --- Identity clustering (HDBSCAN over 512-d face embeddings) ---
HDBSCAN_MIN_CLUSTER = 5
HDBSCAN_MIN_SAMPLES = 1
# Over-split levers (fragments of the same person across lighting/pose). Conservative
# defaults (off); raise per-project. epsilon merges density-similar fragments;
# CLUSTER_MERGE_COSINE runs a centroid-cosine merge post-pass (e.g. 0.93).
HDBSCAN_SELECTION_EPSILON = 0.0
# Centroid-cosine merge post-pass: collapses same-person fragments split across
# lighting/pose. 0.5 measured best (silhouette) on a real reception; 0 disables.
CLUSTER_MERGE_COSINE = 0.5

# --- Multi-criteria picks per series (use-case 2) ---
# Every metric is computed for every photo (see quality.py / score.py); each pick
# weights them differently so context decides — a GROUP photo keeps eyes strict
# (a blink is fatal), while MOMENT lets a great frame beat a blink.
# 'group'    = best group-aware print frame; eyes STRICT (worst-eye + straggler penalty)
# 'everyone' = most people simultaneously eyes-open + smiling + facing (cohesion)
# 'smile'    = biggest smile in the frame (joy)
# 'candid'   = natural / un-posed (present smile + off-axis), soft on eyes
# 'moment'   = the decisive frame; eyes barely matter, rewards expression + sharpness
# 'aesthetic'= highest aesthetic score (color + exposure + sharpness proxy)
PICK_TYPES = ["group", "everyone", "smile", "candid", "moment", "aesthetic"]

# Per-face "looks good" thresholds — drive the plain-language fraction tags
# ("7/8 eyes open") and the straggler penalty.
EYE_OPEN_THR = 0.5
SMILE_THR = 0.35
FRONT_THR = 0.5

# P1 signals (MediaPipe blendshapes + head-pose transform).
POSE_FRONTAL_FALLOFF = 45.0  # deg of combined yaw+pitch that drives frontality to 0
GAZE_AWAY_FALLOFF = 0.6  # mean eyeLook* blendshape drive that drives gaze to 0
DUCHENNE_BASE = 0.6  # mouth-only smile multiplier; full cheek-raise lifts it to 1.0
GAZE_THR = 0.5  # eye-contact tag threshold ("6/8 eye contact")

# P1 light / color / focus signals (pure numpy over stored thumbnails).
CAST_FALLOFF = 40.0  # mean opponent bias (0..255) that reads as a full color cast
HORIZON_MIN_CONC = 0.35  # min edge-orientation concentration to trust a Dutch-tilt
HORIZON_MAX_TILT_DEG = 12.0  # deg of tilt that saturates the horizon signal
HIGHLIGHT_WARN = 0.08  # blown-highlight area fraction that raises a flag
SHADOW_WARN = 0.18  # crushed-shadow area fraction that raises a flag
CAST_WARN = 0.5  # color-cast value that raises a flag
TILT_WARN = 0.5  # horizon-tilt value that raises a flag

# Group pick: eyes stay important. eyes_term = a blend of the area-weighted mean
# (a tiny background blink can't dominate) and the worst eye (a foreground blink hurts),
# minus a per-straggler penalty. Continuous blur floor replaces the old ×0.25 step.
GROUP_EYES_WMEAN = 0.5
GROUP_EYES_MIN = 0.5
STRAGGLER_PEN = 0.05
STRAGGLER_CAP = 4
BLUR_FLOOR_WIDTH = 0.04  # sigmoid half-width for the smooth blur floor

# Moment pick: a great frame beats a blink — eyes are a soft mean, never a gate.
MOMENT_W_JOY = 0.40
MOMENT_W_ENGAGE = 0.15
MOMENT_W_SHARP = 0.30
MOMENT_W_EXPO = 0.15

# Composition (from face bboxes): crop-safety + rule-of-thirds + headroom.
CROP_EDGE_PEN = 0.25  # per-face penalty for a face touching the frame edge

# --- Series grouping (use-case 2: same moment / burst) ---
SERIES_TIME_GAP_S = 10.0  # EXIF gap > this starts a new candidate block
SERIES_COS_THRESHOLD = 0.88  # global-embedding cosine to merge within a time block
SERIES_EMBED_ONLY_COS = 0.92  # tighter cosine to merge when timestamps absent (PNG)

# --- Per-face quality (use-case 1: best face crop of a person) ---
# quality = 0.35*sharp + 0.20*bright + 0.25*eye + 0.15*frontal + 0.05*smile
FACE_W_SHARP = 0.35
FACE_W_BRIGHT = 0.20
FACE_W_EYE = 0.25
FACE_W_FRONTAL = 0.15
FACE_W_SMILE = 0.05

# --- Print score (use-case 2: best whole frame to print) ---
# group-aware: eyes uses MIN over faces (one blink ruins the print)
PRINT_W_SHARP = 0.40
PRINT_W_EXPOSURE = 0.20
PRINT_W_EYES = 0.25  # min(eye_open) over all faces
PRINT_W_EXPR = 0.15  # mean(smile, frontality) over all faces
PRINT_DISQUALIFY_SHARP = 0.15  # normalized global sharpness below this => heavy penalty
PRINT_BLUR_PENALTY = 0.25  # multiply score by this when disqualified

# --- Sharpness normalization ---
SHARPNESS_CAP = 500.0  # legacy hard cap -> [0,1]
SHARPNESS_SQUASH_K = 150.0  # monotone squash scale: 1 - exp(-var/k)

# --- Aesthetic proxy (heuristic; not a learned model) ---
AESTHETIC_W_COLOR = 0.40
AESTHETIC_W_EXPOSURE = 0.30
AESTHETIC_W_SHARP = 0.30
