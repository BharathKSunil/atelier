"""AdaFace IR-101 (WebFace12M) identity embedder — alternative recognition backend.

AdaFace (Kim et al., CVPR'22) is quality-adaptive: it down-weights the margin on
low-quality crops instead of forcing them onto the same hypersphere as sharp faces.
That makes it sturdier than vanilla ArcFace on the blurry / off-pose / badly-lit
faces a wedding set is full of. We use it ONLY to turn an already-aligned 112x112
crop into a 512-d embedding; detection + 5-point alignment stay with insightface.

Load route (route (a) from the task, adapted because mk-minchul/AdaFace is not
pip-installable):
  * Weights: the *original* mk-minchul AdaFace Lightning checkpoint, mirrored on the
    HF Hub as `marcelo-victor/adaface_ir101_webface12m :: adaface_weights.ckpt`,
    fetched via `huggingface_hub.hf_hub_download`. Its state_dict carries the
    backbone under `model.*` (input_layer / body.N.res_layer.* / output_layer) and
    the AdaFace margin head under `head.*` — we keep the backbone, drop the head.
  * Backbone: the IR-101 (IResNet-101) net `build_model('ir_101')` defines in that
    repo, vendored inline below with byte-identical module/key layout so the
    published state_dict loads with strict=True after stripping the `model.` prefix.
    Verified against the checkpoint: input_layer + 49 bottleneck_IR units in stages
    [3,13,30,3] over channels [64,128,256,512] + output_layer(BN,Drop,Flatten,
    Linear(25088->512),BN1d) — no SE modules.

Preprocessing caveats honored (per the verifier): the mk-minchul weights expect a
112x112 crop produced by the standard ArcFace 5-point similarity transform (we reuse
insightface's `norm_crop`), fed as **BGR** with mean/std = 0.5, i.e.
`(img/255 - 0.5) / 0.5` on a BGR float tensor. We do NOT add a separate aligner.

If the checkpoint cannot be downloaded/built in this environment, `get_embedder`
raises a loud RuntimeError — but only when RECOGNITION_MODEL='adaface' actually
selects this path. The default arcface path never imports this module.
"""

import threading

import numpy as np

# Original mk-minchul AdaFace checkpoint mirror (Lightning .ckpt, BGR / mean-std 0.5).
_HF_REPO = "marcelo-victor/adaface_ir101_webface12m"
_HF_FILE = "adaface_weights.ckpt"

_embedder = None
_lock = threading.Lock()


def _conv3x3(in_c, out_c, stride=1):
    import torch.nn as nn

    return nn.Conv2d(in_c, out_c, 3, stride, 1, bias=False)


def _make_bottleneck(in_c, depth, stride):
    """One `bottleneck_IR` unit, matching AdaFace net.py key order exactly.

    res_layer = Sequential(BN(in), Conv3x3(in->depth), BN(depth), PReLU(depth),
                           Conv3x3(depth->depth, stride), BN(depth))
    shortcut  = MaxPool(1, stride) when in==depth else Sequential(Conv1x1(stride), BN)
    forward   = res_layer(x) + shortcut(x)
    """
    import torch.nn as nn

    class _Unit(nn.Module):
        def __init__(self):
            super().__init__()
            self.res_layer = nn.Sequential(
                nn.BatchNorm2d(in_c),
                _conv3x3(in_c, depth, 1),
                nn.BatchNorm2d(depth),
                nn.PReLU(depth),
                _conv3x3(depth, depth, stride),
                nn.BatchNorm2d(depth),
            )
            # Original AdaFace rule: a parameterless MaxPool shortcut whenever the
            # channel count is unchanged (even when stride==2, i.e. the first unit of
            # stage 1); a learned Conv+BN shortcut only when channels grow.
            if in_c == depth:
                self.shortcut_layer = nn.MaxPool2d(1, stride)
            else:
                self.shortcut_layer = nn.Sequential(
                    nn.Conv2d(in_c, depth, 1, stride, bias=False),
                    nn.BatchNorm2d(depth),
                )

        def forward(self, x):
            return self.res_layer(x) + self.shortcut_layer(x)

    return _Unit()


def _build_ir101():
    """IR-101 backbone with the exact module/key layout of the published checkpoint."""
    import torch.nn as nn

    # IR-101: bottleneck_IR units per stage [3, 13, 30, 3]; channels [64,128,256,512].
    # First unit of each stage strides by 2 (the very first too, applied after the
    # stem stride-1 conv). Channel growth at body 3/16/46 gets a learned Conv+BN
    # shortcut; body 0 keeps channels (64->64) so it uses the MaxPool shortcut.
    stage_depths = [64, 128, 256, 512]
    stage_units = [3, 13, 30, 3]

    class _IR101(nn.Module):
        def __init__(self):
            super().__init__()
            self.input_layer = nn.Sequential(
                nn.Conv2d(3, 64, 3, 1, 1, bias=False),
                nn.BatchNorm2d(64),
                nn.PReLU(64),
            )
            units = []
            in_c = 64
            for depth, n in zip(stage_depths, stage_units, strict=False):
                for j in range(n):
                    stride = 2 if j == 0 else 1
                    units.append(_make_bottleneck(in_c, depth, stride))
                    in_c = depth
            self.body = nn.ModuleList(units)
            # Final BN is affine=False in the original net (output_layer.4 carries only
            # running stats, no weight/bias) — keep it so strict loading matches.
            self.output_layer = nn.Sequential(
                nn.BatchNorm2d(512),
                nn.Dropout(0.4),
                nn.Flatten(),
                nn.Linear(512 * 7 * 7, 512),
                nn.BatchNorm1d(512, affine=False),
            )

        def forward(self, x):
            x = self.input_layer(x)
            for unit in self.body:
                x = unit(x)
            return self.output_layer(x)

    return _IR101()


class _AdaFaceEmbedder:
    def __init__(self, device):
        import torch

        self.device = device
        try:
            from huggingface_hub import hf_hub_download
        except Exception as e:  # pragma: no cover - exercised only when hub missing
            raise RuntimeError("AdaFace backend needs huggingface_hub. pip install 'huggingface_hub>=0.20'.") from e

        try:
            ckpt_path = hf_hub_download(repo_id=_HF_REPO, filename=_HF_FILE)
        except Exception as e:
            raise RuntimeError(
                f"AdaFace: could not download IR-101/WebFace12M checkpoint ({_HF_REPO}/{_HF_FILE}): {e}"
            ) from e

        try:
            # weights_only=True: this checkpoint is pure tensors + dict metadata, so we
            # refuse arbitrary-code unpickling (the published .ckpt loads fine this way).
            ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
            raw = ckpt["state_dict"] if isinstance(ckpt, dict) and "state_dict" in ckpt else ckpt
            # Keep backbone (model.*), drop the AdaFace margin head (head.*).
            state = {k[len("model.") :]: v for k, v in raw.items() if k.startswith("model.")}
            if not state:
                raise RuntimeError("checkpoint had no 'model.*' backbone keys")
            net = _build_ir101()
            net.load_state_dict(state, strict=True)
            net.eval().to(device)
        except Exception as e:
            raise RuntimeError(f"AdaFace: failed to build/load IR-101 backbone: {e}") from e

        self.net = net

    def _preprocess(self, face_bgr_112):
        """112x112x3 uint8 BGR aligned crop -> (3,112,112) float32 tensor-ready array.

        mk-minchul weights: BGR input, normalized (img/255 - 0.5)/0.5.
        """
        arr = np.asarray(face_bgr_112)
        if arr.shape[:2] != (112, 112):
            raise ValueError(f"AdaFace expects a 112x112 aligned crop, got {arr.shape}")
        arr = arr.astype(np.float32)
        arr = (arr / 255.0 - 0.5) / 0.5  # BGR, mean/std 0.5
        return arr.transpose(2, 0, 1)  # HWC -> CHW

    def embed_aligned_batch(self, faces_bgr_112):
        """List of 112x112 BGR aligned crops -> (N,512) L2-normalized float32."""
        import torch

        if len(faces_bgr_112) == 0:
            return np.zeros((0, 512), dtype=np.float32)
        batch = np.stack([self._preprocess(f) for f in faces_bgr_112])
        t = torch.from_numpy(batch).to(self.device)
        with torch.no_grad():
            out = self.net(t)
            # AdaFace IR-101 outputs the raw feature; clustering wants unit vectors.
            out = torch.nn.functional.normalize(out, dim=1)
        return out.cpu().numpy().astype(np.float32)

    def embed_aligned(self, face_bgr_112):
        """Single 112x112 BGR aligned crop -> (512,) L2-normalized float32."""
        return self.embed_aligned_batch([face_bgr_112])[0]


def get_embedder(device):
    """Lazily build (and cache) the AdaFace IR-101 embedder.

    Raises RuntimeError (loudly) if the checkpoint can't be downloaded or loaded.
    """
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                _embedder = _AdaFaceEmbedder(device)
    return _embedder
