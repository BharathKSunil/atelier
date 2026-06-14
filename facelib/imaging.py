"""Image loading, downscaling, and EXIF/metadata extraction. Pillow-only."""
import os
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image, ImageOps

IMG_EXTS = {".jpg", ".jpeg", ".png"}

_EXIF_DATETIME_ORIG = 36867   # DateTimeOriginal (Exif IFD)
_EXIF_SUBSEC_ORIG = 37521     # SubSecTimeOriginal
_EXIF_MODEL = 272             # Model (IFD0)
_EXIF_ORIENT = 274            # Orientation (IFD0)


def iter_images(root):
    for p in Path(root).rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            yield p


def load_rgb(path):
    # Apply EXIF orientation so portrait/rotated photos are processed UPRIGHT.
    # Without this, sideways faces wreck detection landmarks + embeddings (rotated
    # photos of the same person look like different people, profiles/blur cluster together).
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def to_gray_array(img):
    return np.asarray(img.convert("L"))


def analysis_resize(img, long_edge):
    """Downscale so the long edge == long_edge. Returns (resized_img, scale)
    where scale = resized/original (<=1.0). No upscaling."""
    w, h = img.size
    scale = long_edge / float(max(w, h))
    if scale >= 1.0:
        return img, 1.0
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    return img.resize((nw, nh), Image.BILINEAR), scale


def read_metadata(path, img):
    """Return (taken_at, exif_time, sub_sec, camera, orientation).

    taken_at  : epoch seconds. EXIF DateTimeOriginal if present, else file mtime.
    exif_time : True if taken_at came from EXIF (reliable for time-blocking),
                False if it's the mtime fallback (e.g. PNG).
    """
    taken_at, exif_time, sub_sec, camera, orientation = None, False, None, None, None
    try:
        exif = Image.open(path).getexif()   # read from original (img may be exif-transposed)
        if exif:
            orientation = exif.get(_EXIF_ORIENT)
            model = exif.get(_EXIF_MODEL)
            camera = str(model).strip() if model is not None else None
            try:
                ifd = exif.get_ifd(ExifTags.IFD.Exif)
            except Exception:
                ifd = {}
            dt = ifd.get(_EXIF_DATETIME_ORIG)
            ss = ifd.get(_EXIF_SUBSEC_ORIG)
            if dt:
                try:
                    taken_at = datetime.strptime(str(dt), "%Y:%m:%d %H:%M:%S").timestamp()
                    exif_time = True
                except ValueError:
                    taken_at = None
            if ss:
                try:
                    sub_sec = int(str(ss).strip()[:3])
                except ValueError:
                    sub_sec = None
    except Exception:
        pass

    if taken_at is None:
        taken_at = os.path.getmtime(path)   # fallback; exif_time stays False
    return taken_at, exif_time, sub_sec, camera, orientation
