"""Constants and tunables. No heavy imports — keep this dependency-free."""
import os
from pathlib import Path


def default_projects_dir():
    """Single source of truth for where projects live: ~/.atelier (override: $ATELIER_HOME)."""
    return os.environ.get("ATELIER_HOME") or str(Path.home() / ".atelier")


# insightface ONNX execution providers. None = auto-detect (CoreML on Apple Silicon
# -> ~2.7x detection / ~16x recognition here; CUDA on nvidia; else CPU).
INSIGHTFACE_PROVIDERS = None

# --- Decode / sizing ---
ANALYSIS_LONG_EDGE = 1536   # downscale long edge for detection + global embedding
THUMB_MAX = 256             # stored face thumbnail max edge (px)
IMAGE_THUMB_MAX = 360       # stored per-image thumbnail max edge (px) — avoids re-decoding originals

# --- Face detection / recognition backend ---
# "insightface" = RetinaFace detector + ArcFace embeddings (buffalo_l) — far fewer
# false positives (jewelry/skin/blur) and much better clustering than MTCNN+FaceNet.
# "mtcnn" = legacy facenet-pytorch fallback.
FACE_BACKEND = "insightface"
INSIGHTFACE_MODEL = "buffalo_l"
INSIGHTFACE_DET_SIZE = 640   # SCRFD standard; larger can MISS frame-filling faces

# Identity-embedding model (A/B switch). Detection always stays SCRFD (insightface);
# this only swaps what produces the 512-d embedding from the aligned 112x112 crop.
# "arcface"  = insightface buffalo_l ArcFace embedding (default, unchanged behavior).
# "adaface"  = mk-minchul AdaFace IR-101 / WebFace12M (quality-adaptive; better on
#              low-quality / varied-pose wedding faces). See facelib/recognition.py.
RECOGNITION_MODEL = "arcface"   # or "adaface"

# Quality gates applied at index time (reject non-faces before they ever cluster):
FACE_DET_THRESHOLD = 0.60   # min detector confidence (drops jewelry/skin false positives)
FACE_MIN_PX = 32            # min bbox side in the analysis image (drops tiny background faces)
FACE_MIN_SHARPNESS = 0.12   # min squashed sharpness (drops out-of-focus blobs)
FACE_MIN_FRONTALITY = 0.35  # min frontality from detector keypoints (drops profiles/ears
                            # whose embeddings are unreliable and pollute clusters)

# legacy MTCNN params (only used when FACE_BACKEND == "mtcnn")
MTCNN_MIN_FACE = 40
MTCNN_THRESHOLDS = [0.6, 0.7, 0.7]

# --- Identity clustering (HDBSCAN over 512-d face embeddings) ---
HDBSCAN_MIN_CLUSTER = 5
HDBSCAN_MIN_SAMPLES = 1
# Over-split levers (fragments of the same person across lighting/pose). Conservative
# defaults (off); raise per-project. epsilon merges density-similar fragments;
# CLUSTER_MERGE_COSINE runs a centroid-cosine merge post-pass (e.g. 0.93).
HDBSCAN_SELECTION_EPSILON = 0.0
CLUSTER_MERGE_COSINE = 0.0

# --- Multi-criteria picks per series (use-case 2) ---
# 'group'    = best group-aware print_score (everyone's eyes open)
# 'aesthetic'= highest aesthetic score (linear head over the DINOv2 embedding)
# 'candid'   = natural / un-posed (lower frontality + present smile)
PICK_TYPES = ["group", "aesthetic", "candid"]

# --- Series grouping (use-case 2: same moment / burst) ---
SERIES_TIME_GAP_S = 10.0       # EXIF gap > this starts a new candidate block
SERIES_COS_THRESHOLD = 0.88    # global-embedding cosine to merge within a time block
SERIES_EMBED_ONLY_COS = 0.92   # tighter cosine to merge when timestamps absent (PNG)

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
PRINT_W_EYES = 0.25     # min(eye_open) over all faces
PRINT_W_EXPR = 0.15     # mean(smile, frontality) over all faces
PRINT_DISQUALIFY_SHARP = 0.15   # normalized global sharpness below this => heavy penalty
PRINT_BLUR_PENALTY = 0.25       # multiply score by this when disqualified

# --- Sharpness normalization ---
SHARPNESS_CAP = 500.0    # legacy hard cap -> [0,1]
SHARPNESS_SQUASH_K = 150.0   # monotone squash scale: 1 - exp(-var/k)

# --- Aesthetic proxy (heuristic; not a learned model) ---
AESTHETIC_W_COLOR = 0.40
AESTHETIC_W_EXPOSURE = 0.30
AESTHETIC_W_SHARP = 0.30
