"""Phase 3 — Score quality and pick the best.

Per face : MediaPipe FaceMesh on the stored thumbnail -> eyes / smile / frontality;
           combined with the full-res face_sharpness from Phase 1 -> quality_score.
           is_best = top quality_score per person  (use-case 1).
Per image: print_score = global sharpness + exposure + group-aware face signals.
           is_best_in_series = top print_score per series  (use-case 2, the print pick).

No original images are re-read here — all signals come from the DB.
"""
import argparse
import io

import numpy as np
from PIL import Image
from tqdm import tqdm

from facelib import db, landmarks, quality

# MediaPipe face-mesh landmark indices (same topology in the Tasks API)
L_EYE = [33, 160, 158, 133, 153, 144]    # p1..p6 for EAR
R_EYE = [362, 385, 387, 263, 373, 380]
LEFT_EYE_C, RIGHT_EYE_C, NOSE = 33, 263, 1
MOUTH_L, MOUTH_R, LIP_TOP, LIP_BOT = 61, 291, 13, 14


def _landmarks(thumb_bytes):
    arr = np.asarray(Image.open(io.BytesIO(thumb_bytes)).convert("RGB"))
    return landmarks.landmarks_px(arr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="faces.db")
    ap.add_argument("--rescore-all", action="store_true",
                    help="recompute per-face quality for ALL faces (default: only new/unscored)")
    args = ap.parse_args()
    conn = db.connect(args.db)

    have_mesh = False
    try:
        landmarks.get_landmarker()
        have_mesh = True
        print("mediapipe FaceLandmarker ready")
    except Exception as e:  # noqa: BLE001
        print(f"mediapipe unavailable ({e}); eye/smile/frontality default to 0.5")

    # ---- per-face quality (per-face & independent of clustering, so cache it:
    #      only score new/unscored faces unless --rescore-all) ----
    where = "" if args.rescore_all else "WHERE quality_score IS NULL"
    faces = list(conn.execute(f"SELECT id, thumbnail, face_sharpness FROM faces {where}"))
    for f in tqdm(faces, desc="faces"):
        eye = sm = frontal = bright = 0.5
        thumb = f["thumbnail"]
        if thumb:
            bright = quality.exposure_score(
                np.asarray(Image.open(io.BytesIO(thumb)).convert("L")))
            if have_mesh:
                pts = _landmarks(thumb)
                if pts is not None:
                    eye = quality.eye_openness(quality.ear(pts[L_EYE]), quality.ear(pts[R_EYE]))
                    frontal = quality.frontality(pts[LEFT_EYE_C], pts[RIGHT_EYE_C], pts[NOSE])
                    sm = quality.smile(pts[MOUTH_L], pts[MOUTH_R], pts[LIP_TOP], pts[LIP_BOT])
        sharp = f["face_sharpness"] or 0.0
        q = quality.face_quality(sharp, bright, eye, frontal, sm)
        conn.execute("UPDATE faces SET eye_open=?, smile=?, frontality=?, quality_score=? WHERE id=?",
                     (eye, sm, frontal, q, f["id"]))
    conn.commit()

    # ---- best face per person ----
    conn.execute("UPDATE faces SET is_best=0")
    for p in conn.execute(
            "SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL AND person_id >= 0"):
        top = conn.execute(
            "SELECT id FROM faces WHERE person_id=? ORDER BY quality_score DESC LIMIT 1",
            (p["person_id"],)).fetchone()
        if top:
            conn.execute("UPDATE faces SET is_best=1 WHERE id=?", (top["id"],))
    conn.commit()

    # ---- per-image print + candid + aesthetic scores ----
    for im in conn.execute(
            """SELECT id, global_sharpness, global_sharpness_raw, exposure_score, thumbnail
               FROM images WHERE processed=1""").fetchall():
        fs = list(conn.execute(
            "SELECT eye_open, smile, frontality FROM faces WHERE image_id=?", (im["id"],)))
        eyes = [r["eye_open"] for r in fs if r["eye_open"] is not None]
        smiles = [r["smile"] or 0.0 for r in fs]
        fronts = [r["frontality"] or 0.0 for r in fs]
        expr = [((r["smile"] or 0.0) + (r["frontality"] or 0.0)) / 2.0 for r in fs]
        ex = im["exposure_score"] or 0.0
        # monotone squash on raw sharpness (no more cap-500 saturation); fall back
        # to the stored normalized value for pre-Phase-1 rows without raw.
        raw = im["global_sharpness_raw"]
        gs = quality.squash_sharpness(raw) if raw is not None else (im["global_sharpness"] or 0.0)
        rgb = None
        if im["thumbnail"]:
            try:
                rgb = np.asarray(Image.open(io.BytesIO(im["thumbnail"])).convert("RGB"))
            except Exception:
                rgb = None
        cs = quality.candid_score(gs, ex, smiles, fronts)
        conn.execute(
            """UPDATE images SET global_sharpness=?, aesthetic_score=?, candid_score=?,
               print_score=? WHERE id=?""",
            (gs, quality.aesthetic_proxy(rgb, gs, ex), cs,
             quality.print_score(gs, ex, eyes, expr), im["id"]))
    conn.commit()

    # ---- 'group' best mirror per series (is_best_in_series; auto picks for all
    #      criteria are derived at read time in the server from the per-image scores) ----
    conn.execute("UPDATE images SET is_best_in_series=0")
    for s in conn.execute("SELECT id FROM series WHERE frame_count>1").fetchall():
        top = conn.execute(
            "SELECT id FROM images WHERE series_id=? ORDER BY print_score DESC LIMIT 1",
            (s["id"],)).fetchone()
        if top:
            conn.execute("UPDATE images SET is_best_in_series=1 WHERE id=?", (top["id"],))
            conn.execute("UPDATE series SET best_image_id=? WHERE id=?", (top["id"], s["id"]))
    conn.commit()
    print("scoring done")


if __name__ == "__main__":
    main()
