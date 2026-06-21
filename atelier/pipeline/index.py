#!/usr/bin/env python3
"""Phase 1 — Index. Decode each photo once (EXIF-uprighted) at full res for
sharpness, downscale for detection + embedding. Resumable; re-running skips
already-processed images.

Per image:
  full-res   -> global sharpness + exposure, per-face crop sharpness
  downscaled -> insightface RetinaFace/SCRFD detect + ArcFace 512-d embed
                (quality-gated) + DINOv2 384-d global embed for burst grouping
"""

import argparse
import io
import os

import numpy as np
from tqdm import tqdm

from atelier import config, db, imaging, landmarks, models, quality


def _pad_crop(pil_img, box, pad=0.4):
    """Crop `box` from a PIL image with `pad` fractional context (for the MediaPipe check)."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    cx1, cy1 = max(0, int(x1 - w * pad)), max(0, int(y1 - h * pad))
    cx2, cy2 = min(pil_img.width, int(x2 + w * pad)), min(pil_img.height, int(y2 + h * pad))
    return pil_img.crop((cx1, cy1, cx2, cy2)).convert("RGB")


def _bg_sharpness(gray_full, boxes):
    """Laplacian variance of the frame with face regions EXCLUDED (not masked, so no
    boundary edge artifact) — the background acutance behind the subject. Pairs with
    per-face sharpness to score subject-vs-background focus (bokeh / focus-miss)."""
    g = np.asarray(gray_full, dtype=np.float64)
    if g.ndim != 2 or min(g.shape) < 3:
        return None
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4.0 * g[1:-1, 1:-1]
    bg = np.ones(lap.shape, dtype=bool)
    for x1, y1, x2, y2 in boxes:  # lap is g[1:-1,1:-1] -> shift box by 1px
        ix1, iy1 = max(0, int(x1) - 1), max(0, int(y1) - 1)
        ix2, iy2 = min(lap.shape[1], int(x2)), min(lap.shape[0], int(y2))
        if ix2 > ix1 and iy2 > iy1:
            bg[iy1:iy2, ix1:ix2] = False
    return float(lap[bg].var()) if int(bg.sum()) >= 16 else None


def _crop_full(full_img, box, scale):
    """Map a box in analysis coords back to original coords and crop full-res."""
    x1, y1, x2, y2 = (v / scale for v in box)
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2 = min(full_img.width, int(x2))
    y2 = min(full_img.height, int(y2))
    if x2 <= x1 or y2 <= y1:
        return None, (x1, y1, x2, y2)
    return full_img.crop((x1, y1, x2, y2)), (x1, y1, x2, y2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", required=True, help="Root folder of nested photos")
    ap.add_argument("--db", default="faces.db")
    ap.add_argument(
        "--retry-errors", action="store_true", help="Re-process images previously marked as errored (processed=2)"
    )
    ap.add_argument("--det-threshold", type=float, default=config.FACE_DET_THRESHOLD)
    ap.add_argument("--min-px", type=int, default=config.FACE_MIN_PX)
    ap.add_argument("--min-sharpness", type=float, default=config.FACE_MIN_SHARPNESS)
    ap.add_argument("--min-frontality", type=float, default=config.FACE_MIN_FRONTALITY)
    args = ap.parse_args()
    det_thr, min_px, min_sharp = args.det_threshold, args.min_px, args.min_sharpness
    min_front = args.min_frontality

    conn = db.init_db(args.db)
    device = models.get_device()
    print(f"device = {device}")

    cur = conn.cursor()
    if args.retry_errors:
        n = cur.execute("UPDATE images SET processed=0 WHERE processed=2").rowcount
        conn.commit()
        print(f"reset {n} errored images for retry")
    existing = {r["path"] for r in cur.execute("SELECT path FROM images")}
    added = 0
    for p in imaging.iter_images(args.photos):
        sp = str(p)
        if sp not in existing:
            cur.execute("INSERT OR IGNORE INTO images(path, processed) VALUES(?, 0)", (sp,))
            added += 1
    conn.commit()
    print(f"enqueued {added} new images")

    pending = list(cur.execute("SELECT id, path FROM images WHERE processed = 0"))
    print(f"{len(pending)} pending")

    for row in tqdm(pending):
        iid, path = row["id"], row["path"]
        try:
            # idempotent re-index: clear this image's faces (and any stale override
            # anchors on them — face ids are reassigned on re-insert, and the FK would
            # otherwise block the delete).
            cur.execute(
                """DELETE FROM person_overrides WHERE face_id IN
                           (SELECT id FROM faces WHERE image_id=?)""",
                (iid,),
            )
            cur.execute("DELETE FROM faces WHERE image_id=?", (iid,))
            img = imaging.load_rgb(path)
            W, H = img.size
            taken_at, exif_time, sub_sec, camera, orient = imaging.read_metadata(path, img)

            gray_full = imaging.to_gray_array(img)
            graw = quality.laplacian_var(gray_full)
            gsharp = quality.norm_sharpness(graw)
            expo = quality.exposure_score(gray_full)

            ithumb = img.copy()
            ithumb.thumbnail((config.IMAGE_THUMB_MAX, config.IMAGE_THUMB_MAX))
            ibuf = io.BytesIO()
            ithumb.save(ibuf, "JPEG", quality=80)

            small, scale = imaging.analysis_resize(img, config.ANALYSIS_LONG_EDGE)
            gemb = models.embed_global(small, device)
            dets = models.detect_and_embed(small, device)

            # gate out non-faces before they ever cluster: detector confidence + size
            # + box shape + keypoint geometry + (for borderline) a MediaPipe second opinion.
            face_rows = []
            for d in dets:
                if d["score"] < det_thr:
                    continue
                x1, y1, x2, y2 = d["bbox"]
                w, h = x2 - x1, y2 - y1
                if min(w, h) < min_px:
                    continue
                kps = d.get("kps")
                if kps is not None and quality.frontality(kps[0], kps[1], kps[2]) < min_front:
                    continue  # drop profiles / ears (unreliable embedding)
                # Non-face filters apply ONLY to borderline detections; SCRFD >= 0.80 is
                # trusted (keeps real profiles/odd crops). Hair/fabric sit at 0.65-0.80.
                if d["score"] < config.FACE_DET_AUTO_ACCEPT:
                    if not (0.6 <= w / max(h, 1e-6) <= 1.7):  # faces ~square-ish
                        continue
                    if kps is not None and not quality.kps_plausible(kps, d["bbox"]):
                        continue  # impossible eye/nose/mouth layout
                    if config.FACE_VERIFY_LANDMARKS and not landmarks.has_face(np.asarray(_pad_crop(small, d["bbox"]))):
                        continue  # MediaPipe second opinion: no face here
                crop, (ox1, oy1, ox2, oy2) = _crop_full(img, d["bbox"], scale)
                if crop is None:
                    continue
                fraw = quality.laplacian_var(imaging.to_gray_array(crop))
                if quality.squash_sharpness(fraw) < min_sharp:
                    continue  # drop out-of-focus blobs
                thumb = crop.copy()
                thumb.thumbnail((config.THUMB_MAX, config.THUMB_MAX))
                buf = io.BytesIO()
                thumb.save(buf, "JPEG", quality=85)
                face_rows.append(
                    (
                        ox1,
                        oy1,
                        ox2,
                        oy2,
                        d["score"],
                        d["embedding"].tobytes(),
                        buf.getvalue(),
                        quality.norm_sharpness(fraw),
                        fraw,
                    )
                )

            bgsharp = _bg_sharpness(gray_full, [(fr[0], fr[1], fr[2], fr[3]) for fr in face_rows])
            cur.execute(
                """UPDATE images SET file_size=?, width=?, height=?, taken_at=?, exif_time=?,
                   sub_sec=?, camera=?, orientation=?, global_embedding=?, global_sharpness=?,
                   global_sharpness_raw=?, exposure_score=?, thumbnail=?, face_count=?,
                   bg_sharpness_raw=?, processed=1, error_msg=NULL WHERE id=?""",
                (
                    os.path.getsize(path),
                    W,
                    H,
                    taken_at,
                    1 if exif_time else 0,
                    sub_sec,
                    camera,
                    orient,
                    gemb.tobytes(),
                    gsharp,
                    graw,
                    expo,
                    ibuf.getvalue(),
                    len(face_rows),
                    bgsharp,
                    iid,
                ),
            )
            for fi, fr in enumerate(face_rows):
                cur.execute(
                    """INSERT INTO faces(image_id, face_index, bbox_x1, bbox_y1, bbox_x2,
                       bbox_y2, confidence, embedding, thumbnail, face_sharpness, face_sharpness_raw)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (iid, fi, *fr),
                )
            conn.commit()
        except Exception as e:  # noqa: BLE001 — record and continue, stay resumable
            conn.rollback()
            cur.execute("UPDATE images SET processed=2, error_msg=? WHERE id=?", (str(e)[:500], iid))
            conn.commit()

    done = cur.execute("SELECT COUNT(*) n FROM images WHERE processed=1").fetchone()["n"]
    err = cur.execute("SELECT COUNT(*) n FROM images WHERE processed=2").fetchone()["n"]
    nfaces = cur.execute("SELECT COUNT(*) n FROM faces").fetchone()["n"]
    print(f"done: {done} indexed, {nfaces} faces, {err} errors")


if __name__ == "__main__":
    main()
