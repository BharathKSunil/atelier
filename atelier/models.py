"""Lazy model loaders. Heavy imports (torch, insightface) live inside functions so
the pure modules (quality, series, db, imaging) stay importable without them."""

import os

# Some ops (DINOv2 / Resnet adaptive pooling) aren't implemented on Apple MPS;
# fall back to CPU for just those ops instead of crashing. Must be set before torch loads.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np

from . import config

_dino = None
_insight = None

_DINO_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_DINO_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def get_device():
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def dino(device):
    global _dino
    if _dino is None:
        import torch

        _dino = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14").eval().to(device)
    return _dino


def _onnx_providers():
    if config.INSIGHTFACE_PROVIDERS:
        return list(config.INSIGHTFACE_PROVIDERS)
    try:
        import onnxruntime as ort

        avail = ort.get_available_providers()
    except Exception:
        avail = []
    for gpu in ("CoreMLExecutionProvider", "CUDAExecutionProvider"):
        if gpu in avail:
            return [gpu, "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def insight_app():
    global _insight
    if _insight is None:
        import insightface

        provs = _onnx_providers()
        _insight = insightface.app.FaceAnalysis(
            name=config.INSIGHTFACE_MODEL, allowed_modules=["detection", "recognition"], providers=provs
        )
        # ctx_id=0 lets a GPU/CoreML provider bind; -1 forces CPU context.
        ctx = -1 if provs[0] == "CPUExecutionProvider" else 0
        _insight.prepare(ctx_id=ctx, det_size=(config.INSIGHTFACE_DET_SIZE, config.INSIGHTFACE_DET_SIZE))
    return _insight


def detect_and_embed(pil_img, device):
    """Detection + identity embedding (insightface SCRFD + ArcFace, or AdaFace).

    Returns a list of {bbox:(x1,y1,x2,y2) in pil_img coords, score:float,
    embedding:np.float32[512] (L2-normalized)}.
    """
    app = insight_app()
    bgr = np.ascontiguousarray(np.asarray(pil_img)[:, :, ::-1])  # RGB->BGR
    faces = app.get(bgr)
    if config.RECOGNITION_MODEL == "adaface":
        # Keep SCRFD detection + its 5-pt landmarks, but re-align each face with the
        # standard ArcFace similarity transform and embed it with AdaFace IR-101.
        from insightface.utils.face_align import norm_crop

        from . import recognition

        embedder = recognition.get_embedder(device)
        return [
            {
                "bbox": tuple(float(v) for v in f.bbox),
                "score": float(f.det_score),
                "embedding": embedder.embed_aligned(norm_crop(bgr, f.kps)),
                "kps": np.asarray(f.kps, dtype=np.float64),
            }
            for f in faces
        ]
    return [
        {
            "bbox": tuple(float(v) for v in f.bbox),
            "score": float(f.det_score),
            "embedding": f.normed_embedding.astype(np.float32),
            "kps": np.asarray(f.kps, dtype=np.float64),
        }  # 5 pts: eyes, nose, mouth
        for f in faces
    ]


def embed_global(img, device):
    """384-d L2-normalized DINOv2 CLS embedding for whole-scene similarity."""
    import torch

    d = dino(device)
    im = img.resize((224, 224))  # 224 = 16 * 14, valid patch grid
    arr = (np.asarray(im).astype(np.float32) / 255.0 - _DINO_MEAN) / _DINO_STD
    t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(device)
    with torch.no_grad():
        feat = d(t).cpu().numpy().astype(np.float32)[0]
    return (feat / (np.linalg.norm(feat) + 1e-9)).astype(np.float32)
