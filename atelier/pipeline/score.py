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

from atelier import config, db, landmarks, quality

# MediaPipe face-mesh landmark indices (same topology in the Tasks API)
L_EYE = [33, 160, 158, 133, 153, 144]  # p1..p6 for EAR
R_EYE = [362, 385, 387, 263, 373, 380]
LEFT_EYE_C, RIGHT_EYE_C, NOSE = 33, 263, 1
MOUTH_L, MOUTH_R, LIP_TOP, LIP_BOT = 61, 291, 13, 14

# ARKit blendshape category names (P1 robust signals)
BLINK_L, BLINK_R = "eyeBlinkLeft", "eyeBlinkRight"
SMILE_L, SMILE_R = "mouthSmileLeft", "mouthSmileRight"
CHEEK_L, CHEEK_R = "cheekSquintLeft", "cheekSquintRight"
LOOK_KEYS = [
    "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeLookDownLeft",
    "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeLookDownRight",
]  # fmt: skip
JAW = "jawOpen"  # P2 grimace / talking blendshapes (max of left/right)
BROW = ("browDownLeft", "browDownRight")
SNEER = ("noseSneerLeft", "noseSneerRight")
FROWN = ("mouthFrownLeft", "mouthFrownRight")


def _signals(thumb_bytes):
    arr = np.asarray(Image.open(io.BytesIO(thumb_bytes)).convert("RGB"))
    return landmarks.face_signals(arr)


def _emb(buf):
    return np.frombuffer(buf, dtype=np.float32) if buf else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="faces.db")
    ap.add_argument(
        "--rescore-all",
        action="store_true",
        help="recompute per-face quality for ALL faces (default: only new/unscored)",
    )
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
        eye_l = eye_r = yaw = pitch = roll = gaze = genuine = grim = mouth = None
        thumb = f["thumbnail"]
        if thumb:
            bright = quality.exposure_score(np.asarray(Image.open(io.BytesIO(thumb)).convert("L")))
            if have_mesh:
                sig = _signals(thumb)
                if sig is not None:
                    pts, blend, mtx = sig["pts"], sig["blend"], sig["matrix"]
                    # eyes: prefer the eyeBlink blendshapes, else fall back to EAR geometry
                    if BLINK_L in blend and BLINK_R in blend:
                        eye_l, eye_r = 1.0 - blend[BLINK_L], 1.0 - blend[BLINK_R]
                        eye = quality.eye_open_from_blink(blend[BLINK_L], blend[BLINK_R])
                    else:
                        eye = quality.eye_openness(quality.ear(pts[L_EYE]), quality.ear(pts[R_EYE]))
                    # frontality: prefer head-pose Euler, else nose-offset geometry
                    if mtx is not None:
                        yaw, pitch, roll = quality.euler_from_matrix(mtx)
                        frontal = quality.pose_frontality(yaw, pitch, roll)
                    else:
                        frontal = quality.frontality(pts[LEFT_EYE_C], pts[RIGHT_EYE_C], pts[NOSE])
                    # gaze + Duchenne smile (blendshape-only; null when unavailable)
                    if any(k in blend for k in LOOK_KEYS):
                        gaze = quality.gaze_at_camera([blend.get(k) for k in LOOK_KEYS])
                    if SMILE_L in blend:
                        genuine = quality.genuine_smile(
                            blend.get(SMILE_L, 0.0), blend.get(SMILE_R, 0.0),
                            blend.get(CHEEK_L, 0.0), blend.get(CHEEK_R, 0.0),
                        )
                    # keep the lip-ratio `smile` for display continuity
                    sm = quality.smile(pts[MOUTH_L], pts[MOUTH_R], pts[LIP_TOP], pts[LIP_BOT])
                    # P2 awkward-transient + talking (blendshape-only)
                    if blend:
                        grim = quality.grimace(
                            max(blend.get(BROW[0], 0.0), blend.get(BROW[1], 0.0)),
                            max(blend.get(SNEER[0], 0.0), blend.get(SNEER[1], 0.0)),
                            max(blend.get(FROWN[0], 0.0), blend.get(FROWN[1], 0.0)),
                        )
                        mouth = quality.mouth_open_talking(
                            blend.get(JAW, 0.0), max(blend.get(SMILE_L, 0.0), blend.get(SMILE_R, 0.0))
                        )
        sharp = f["face_sharpness"] or 0.0
        q = quality.face_quality(sharp, bright, eye, frontal, sm)
        conn.execute(
            """UPDATE faces SET eye_open=?, smile=?, frontality=?, quality_score=?,
               eye_left=?, eye_right=?, yaw=?, pitch=?, roll=?, gaze=?, genuine_smile=?,
               face_exposure=?, grimace=?, mouth_open=? WHERE id=?""",
            (eye, sm, frontal, q, eye_l, eye_r, yaw, pitch, roll, gaze, genuine, bright, grim, mouth, f["id"]),
        )
    conn.commit()

    # ---- best face per person ----
    conn.execute("UPDATE faces SET is_best=0")
    for p in conn.execute("SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL AND person_id >= 0"):
        top = conn.execute(
            "SELECT id FROM faces WHERE person_id=? ORDER BY quality_score DESC LIMIT 1", (p["person_id"],)
        ).fetchone()
        if top:
            conn.execute("UPDATE faces SET is_best=1 WHERE id=?", (top["id"],))
    conn.commit()

    # ---- per-image metrics: every photo analysed on every signal ("all the tags").
    #      The SAME per-face inputs feed every criterion; only the weighting differs,
    #      so a group photo stays eyes-strict while 'moment' lets a great frame win. ----
    for im in conn.execute(
        """SELECT id, global_sharpness, global_sharpness_raw, exposure_score, thumbnail, width, height,
                  bg_sharpness_raw
               FROM images WHERE processed=1"""
    ).fetchall():
        fr = list(
            conn.execute(
                """SELECT eye_open, smile, frontality, gaze, face_exposure, face_sharpness_raw,
                          bbox_x1, bbox_y1, bbox_x2, bbox_y2
                       FROM faces WHERE image_id=?""",
                (im["id"],),
            )
        )
        faces = [
            {
                "eye": r["eye_open"] if r["eye_open"] is not None else 0.5,
                "smile": r["smile"] or 0.0,
                "front": r["frontality"] or 0.0,
                "area": quality.face_area((r["bbox_x1"] or 0, r["bbox_y1"] or 0, r["bbox_x2"] or 0, r["bbox_y2"] or 0)),
            }
            for r in fr
        ]
        bboxes = [
            (r["bbox_x1"], r["bbox_y1"], r["bbox_x2"], r["bbox_y2"])
            for r in fr
            if None not in (r["bbox_x1"], r["bbox_y1"], r["bbox_x2"], r["bbox_y2"])
        ]
        eyes = [f["eye"] for f in faces]
        smiles = [f["smile"] for f in faces]
        fronts = [f["front"] for f in faces]
        gazes = [r["gaze"] for r in fr if r["gaze"] is not None]
        ex = im["exposure_score"] or 0.0
        # monotone squash on raw sharpness (no more cap-500 saturation); fall back
        # to the stored normalized value for pre-Phase-1 rows without raw.
        raw = im["global_sharpness_raw"]
        gs = quality.squash_sharpness(raw) if raw is not None else (im["global_sharpness"] or 0.0)
        rgb = gray = None
        if im["thumbnail"]:
            try:
                pil = Image.open(io.BytesIO(im["thumbnail"]))
                rgb = np.asarray(pil.convert("RGB"))
                gray = np.asarray(pil.convert("L"))
            except Exception:
                rgb = gray = None
        px = float((im["width"] or 1) * (im["height"] or 1))
        subject_size = (max((f["area"] for f in faces), default=0.0) / px) if faces else None
        # P1 light / color / focus signals (over the stored thumbnail + per-face stats)
        highlight = quality.highlight_frac(gray) if gray is not None else None
        shadow = quality.shadow_frac(gray) if gray is not None else None
        contrast = quality.global_contrast(gray) if gray is not None else None
        tilt = quality.horizon_tilt(gray) if gray is not None else None
        cast = quality.color_cast(rgb) if rgb is not None else None
        hue_var = quality.hue_variance(rgb) if rgb is not None else None
        skin_exp = quality.skin_exposure_agg([r["face_exposure"] for r in fr])
        # bokeh: the largest (subject) face's sharpness vs the background acutance
        subj_sharp = None
        if fr:
            subj = max(fr, key=lambda r: quality.face_area(
                (r["bbox_x1"] or 0, r["bbox_y1"] or 0, r["bbox_x2"] or 0, r["bbox_y2"] or 0)))
            subj_sharp = subj["face_sharpness_raw"]
        bokeh = quality.bokeh_ratio(subj_sharp, im["bg_sharpness_raw"])
        # P2/P3 scene signals over the thumbnail (face boxes mapped to thumbnail coords)
        warm = rim = clut = sym = mot = None
        if gray is not None and rgb is not None:
            th, tw = gray.shape
            sx, sy = tw / float(im["width"] or tw), th / float(im["height"] or th)
            tboxes = [(b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy) for b in bboxes]
            warm = quality.warmth(rgb)
            clut = quality.clutter(gray, tboxes)
            sym = quality.symmetry(gray)
            mot = quality.motion_blur(gray)
            subj_box = max(tboxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), default=None)
            rim = quality.rim_light(gray, subj_box)
        conn.execute(
            """UPDATE images SET global_sharpness=?, aesthetic_score=?, candid_score=?, print_score=?,
               moment_score=?, cohesion=?, joy=?, comp_score=?,
               eyes_open_frac=?, smile_frac=?, front_frac=?, gaze_frac=?, eyes_min=?, subject_size=?,
               highlight_frac=?, shadow_frac=?, contrast=?, color_cast=?, hue_var=?, horizon_tilt=?,
               skin_exposure=?, bokeh=?,
               warmth=?, rim_light=?, clutter=?, symmetry=?, motion_blur=? WHERE id=?""",
            (
                gs,
                quality.aesthetic_proxy(rgb, gs, ex),
                quality.candid_score(gs, ex, faces),
                quality.print_score(gs, ex, faces),
                quality.moment_score(gs, ex, faces),
                quality.cohesion_score(faces),
                quality.joy_score(faces),
                quality.composition_score(bboxes, im["width"], im["height"]),
                quality.fraction_at_least(eyes, config.EYE_OPEN_THR),
                quality.fraction_at_least(smiles, config.SMILE_THR),
                quality.fraction_at_least(fronts, config.FRONT_THR),
                quality.fraction_at_least(gazes, config.GAZE_THR),
                (min(eyes) if eyes else None),
                subject_size,
                highlight,
                shadow,
                contrast,
                cast,
                hue_var,
                tilt,
                skin_exp,
                bokeh,
                warm,
                rim,
                clut,
                sym,
                mot,
                im["id"],
            ),
        )
    conn.commit()

    # ---- within-burst near-duplicate (redundancy) from the stored DINOv2 embeddings ----
    for s in conn.execute("SELECT id FROM series WHERE frame_count>1").fetchall():
        rows = list(conn.execute("SELECT id, global_embedding FROM images WHERE series_id=?", (s["id"],)))
        embs = [_emb(r["global_embedding"]) for r in rows]
        for i, r in enumerate(rows):
            others = [embs[j] for j in range(len(rows)) if j != i]
            red = quality.max_redundancy(embs[i], others) if embs[i] is not None else None
            conn.execute("UPDATE images SET redundancy=? WHERE id=?", (red, r["id"]))
    conn.commit()

    # ---- 'group' best mirror per series (is_best_in_series; auto picks for all
    #      criteria are derived at read time in the server from the per-image scores) ----
    conn.execute("UPDATE images SET is_best_in_series=0")
    for s in conn.execute("SELECT id FROM series WHERE frame_count>1").fetchall():
        top = conn.execute(
            "SELECT id FROM images WHERE series_id=? ORDER BY print_score DESC LIMIT 1", (s["id"],)
        ).fetchone()
        if top:
            conn.execute("UPDATE images SET is_best_in_series=1 WHERE id=?", (top["id"],))
            conn.execute("UPDATE series SET best_image_id=? WHERE id=?", (top["id"], s["id"]))
    conn.commit()
    print("scoring done")


if __name__ == "__main__":
    main()
