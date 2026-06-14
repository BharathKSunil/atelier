"""Face landmark extraction via MediaPipe Tasks API (FaceLandmarker).

The legacy `mediapipe.solutions.face_mesh` API was removed in recent mediapipe
releases; this uses the current Tasks API. Returns the same 478-point face-mesh
topology, so the EAR / frontality / smile landmark indices are unchanged.
The `.task` model bundle is downloaded once on first use.
"""
import os
import urllib.request

import numpy as np

_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
              "face_landmarker/float16/1/face_landmarker.task")
_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
_MODEL_PATH = os.path.join(_MODEL_DIR, "face_landmarker.task")

_landmarker = None


def _ensure_model():
    if not os.path.exists(_MODEL_PATH):
        os.makedirs(_MODEL_DIR, exist_ok=True)
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    return _MODEL_PATH


def get_landmarker():
    global _landmarker
    if _landmarker is None:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        opts = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=_ensure_model()),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
        )
        _landmarker = vision.FaceLandmarker.create_from_options(opts)
    return _landmarker


def landmarks_px(rgb_array):
    """rgb_array: HxWx3 uint8 RGB. Returns (N, 2) pixel coords, or None if no face."""
    import mediapipe as mp
    res = get_landmarker().detect(
        mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb_array)))
    if not res.face_landmarks:
        return None
    h, w = rgb_array.shape[:2]
    return np.array([[p.x * w, p.y * h] for p in res.face_landmarks[0]], dtype=np.float64)


def has_face(rgb_array):
    """Second-opinion face/non-face check: True iff MediaPipe also finds a face on
    the crop. Hair/fabric/backs-of-heads have no landmark geometry -> False."""
    try:
        return landmarks_px(rgb_array) is not None
    except Exception:
        return True   # if mediapipe is unavailable, don't block detection
