"""Lazy model loaders. Heavy imports (torch, facenet) live inside functions so
the pure modules (quality, series, db, imaging) stay importable without them."""
import os

# Some ops (DINOv2 / Resnet adaptive pooling) aren't implemented on Apple MPS;
# fall back to CPU for just those ops instead of crashing. Must be set before torch loads.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np

from . import config

_mtcnn = None
_resnet = None
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


def mtcnn(device):
    # MTCNN's adaptive pooling isn't implemented for non-divisible inputs on Apple
    # MPS (pytorch #96056), so detection always runs on CPU. It's a small net —
    # cheap on CPU — while the heavy embeddings (Resnet, DINOv2) stay on the GPU.
    global _mtcnn
    if _mtcnn is None:
        from facenet_pytorch import MTCNN
        _mtcnn = MTCNN(
            keep_all=True, device="cpu", post_process=False,
            min_face_size=config.MTCNN_MIN_FACE, thresholds=config.MTCNN_THRESHOLDS,
        )
    return _mtcnn


def resnet(device):
    global _resnet
    if _resnet is None:
        from facenet_pytorch import InceptionResnetV1
        _resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)
    return _resnet


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
            name=config.INSIGHTFACE_MODEL,
            allowed_modules=["detection", "recognition"],
            providers=provs)
        # ctx_id=0 lets a GPU/CoreML provider bind; -1 forces CPU context.
        ctx = -1 if provs[0] == "CPUExecutionProvider" else 0
        _insight.prepare(ctx_id=ctx,
                         det_size=(config.INSIGHTFACE_DET_SIZE, config.INSIGHTFACE_DET_SIZE))
    return _insight


def detect_and_embed(pil_img, device):
    """Backend-agnostic detection + identity embedding.

    Returns a list of {bbox:(x1,y1,x2,y2) in pil_img coords, score:float,
    embedding:np.float32[512] (L2-normalized)}.
    """
    if config.FACE_BACKEND == "insightface":
        app = insight_app()
        bgr = np.ascontiguousarray(np.asarray(pil_img)[:, :, ::-1])   # RGB->BGR
        faces = app.get(bgr)
        if config.RECOGNITION_MODEL == "adaface":
            # Keep SCRFD detection + its 5-pt landmarks, but re-align each face with the
            # standard ArcFace similarity transform and embed it with AdaFace IR-101.
            from insightface.utils.face_align import norm_crop

            from . import recognition
            embedder = recognition.get_embedder(device)
            return [{"bbox": tuple(float(v) for v in f.bbox),
                     "score": float(f.det_score),
                     "embedding": embedder.embed_aligned(norm_crop(bgr, f.kps)),
                     "kps": np.asarray(f.kps, dtype=np.float64)}
                    for f in faces]
        return [{"bbox": tuple(float(v) for v in f.bbox),
                 "score": float(f.det_score),
                 "embedding": f.normed_embedding.astype(np.float32),
                 "kps": np.asarray(f.kps, dtype=np.float64)}   # 5 pts: eyes, nose, mouth
                for f in faces]
    # legacy MTCNN + FaceNet
    boxes, probs, _ = detect_faces(pil_img, device)
    if boxes is None or len(boxes) == 0:
        return []
    embs = embed_faces(pil_img, boxes, device)
    embs = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    return [{"bbox": tuple(float(v) for v in b),
             "score": float(probs[i]) if probs[i] is not None else 0.0,
             "embedding": embs[i].astype(np.float32), "kps": None}
            for i, b in enumerate(boxes)]


def detect_faces(img, device):
    """Return (boxes, probs, landmarks) on a PIL image. Any may be None if no faces."""
    return mtcnn(device).detect(img, landmarks=True)


def embed_faces(img, boxes, device):
    """(N,512) float32 identity embeddings for given boxes on PIL img."""
    import torch
    from facenet_pytorch import extract_face
    if boxes is None or len(boxes) == 0:
        return np.zeros((0, 512), dtype=np.float32)
    r = resnet(device)
    crops = []
    for b in boxes:
        face = extract_face(img, b, image_size=160)   # 3x160x160, 0..255
        crops.append((face - 127.5) / 128.0)
    batch = torch.stack(crops).to(device)
    with torch.no_grad():
        emb = r(batch).cpu().numpy().astype(np.float32)
    return emb


def embed_global(img, device):
    """384-d L2-normalized DINOv2 CLS embedding for whole-scene similarity."""
    import torch
    d = dino(device)
    im = img.resize((224, 224))   # 224 = 16 * 14, valid patch grid
    arr = (np.asarray(im).astype(np.float32) / 255.0 - _DINO_MEAN) / _DINO_STD
    t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(device)
    with torch.no_grad():
        feat = d(t).cpu().numpy().astype(np.float32)[0]
    return (feat / (np.linalg.norm(feat) + 1e-9)).astype(np.float32)
