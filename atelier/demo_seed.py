#!/usr/bin/env python3
"""Seed a synthetic demo DB so the web UI can be viewed without running the
model pipeline. Draws fake faces + bursts with PIL (no torch/mediapipe).

  python -m atelier.demo_seed --db demo.db --photos ./demo_photos
  python -m atelier.server --projects-dir ~/.atelier
"""
import argparse
import io
import os
import random

from PIL import Image, ImageDraw

from atelier import db, projects

random.seed(7)

PERSON_COLORS = [(232, 167, 92), (120, 180, 220), (200, 140, 200)]
PERSON_NAMES = ["Aunt Carol", None, "Best Man Joe"]   # None => stays "Person N"


def draw_face(size, skin, *, eyes_open=True, smiling=True, sharp=True, bright=1.0):
    img = Image.new("RGB", (size, size), (28, 30, 36))
    d = ImageDraw.Draw(img)
    cx = cy = size // 2
    r = int(size * 0.36)
    sk = tuple(int(c * bright) for c in skin)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=sk)            # head
    ey = cy - r // 4
    ex = r // 2
    for sx in (-ex, ex):
        if eyes_open:
            d.ellipse([cx + sx - 11, ey - 8, cx + sx + 11, ey + 8], fill=(250, 250, 250))
            d.ellipse([cx + sx - 5, ey - 5, cx + sx + 5, ey + 5], fill=(40, 40, 50))
        else:
            d.line([cx + sx - 11, ey, cx + sx + 11, ey], fill=(40, 40, 50), width=3)
    my = cy + r // 2
    if smiling:
        d.arc([cx - ex, my - 12, cx + ex, my + 14], 20, 160, fill=(120, 40, 40), width=4)
    else:
        d.line([cx - ex // 2, my, cx + ex // 2, my], fill=(120, 40, 40), width=4)
    if not sharp:                                                    # cheap blur
        img = img.resize((size // 6, size // 6)).resize((size, size))
    return img


def make_photo(path, skin, label, *, eyes_open=True, sharp=True, bright=1.0):
    W, H = 800, 600
    img = Image.new("RGB", (W, H))
    for y in range(H):                                              # gradient bg
        c = int(40 + 40 * y / H)
        ImageDraw.Draw(img).line([(0, y), (W, y)], fill=(c, c + 6, c + 14))
    face = draw_face(360, skin, eyes_open=eyes_open, smiling=True, sharp=sharp, bright=bright)
    img.paste(face, (W // 2 - 180, H // 2 - 180))
    ImageDraw.Draw(img).text((16, 16), label, fill=(230, 230, 235))
    img.save(path, "JPEG", quality=90)
    bbox = (W // 2 - 150, H // 2 - 150, W // 2 + 150, H // 2 + 150)
    thumb = img.crop(bbox).resize((220, 220))
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=85)
    return bbox, buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="demo.db")
    ap.add_argument("--photos", default="./demo_photos")
    ap.add_argument("--projects-dir", help="If set, register a project here instead of a bare --db")
    ap.add_argument("--name", default="Demo")
    args = ap.parse_args()

    os.makedirs(args.photos, exist_ok=True)
    if args.projects_dir:
        proj = projects.register_existing(args.projects_dir, args.name, args.photos)
        db_file = projects.db_path(args.projects_dir, proj["slug"])
        print(f"registered project '{proj['slug']}'")
    else:
        db_file = args.db
    if os.path.exists(db_file):
        os.remove(db_file)
    conn = db.init_db(db_file)

    # ---- People (use-case 1): 3 persons x 4 photos ----
    for pid, (skin, name) in enumerate(zip(PERSON_COLORS, PERSON_NAMES)):
        conn.execute("INSERT INTO persons(id, display_name) VALUES(?,?)",
                     (pid, name or f"Person {pid}"))
        quals = sorted([random.uniform(0.45, 0.95) for _ in range(4)], reverse=True)
        for k, q in enumerate(quals):
            path = os.path.abspath(os.path.join(args.photos, f"person{pid}_{k}.jpg"))
            bbox, thumb = make_photo(path, skin, f"{name or 'Person '+str(pid)} #{k}",
                                     eyes_open=(k != 3), sharp=(k != 3), bright=0.7 + 0.3 * q)
            cur = conn.execute(
                "INSERT INTO images(path, processed, width, height) VALUES(?,1,800,600)", (path,))
            iid = cur.lastrowid
            conn.execute(
                """INSERT INTO faces(image_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                   confidence, thumbnail, person_id, quality_score, is_best)
                   VALUES(?,0,?,?,?,?,0.99,?,?,?,?)""",
                (iid, *bbox, thumb, pid, q, 1 if k == 0 else 0))

    # ---- Series (use-case 2): 2 bursts ----
    bursts = [
        ("Ceremony kiss", (232, 167, 92), 4),
        ("Group toast",   (120, 180, 220), 3),
    ]
    for sid, (label, skin, n) in enumerate(bursts):
        best_iid, best_score = None, -1.0
        member_ids = []
        for k in range(n):
            is_blink = (k == n - 1)                                  # last frame: someone blinks
            sharp = (k != 1)                                         # frame 1: motion blur
            bright = 0.7 + 0.1 * k
            path = os.path.abspath(os.path.join(args.photos, f"series{sid}_{k}.jpg"))
            bbox, thumb = make_photo(path, skin, f"{label} — frame {k}",
                                     eyes_open=not is_blink, sharp=sharp, bright=bright)
            gsharp = 0.08 if not sharp else random.uniform(0.55, 0.9)
            expo = min(1.0, bright)
            eyes = 0.1 if is_blink else 0.9
            pscore = (0.40 * gsharp + 0.20 * expo + 0.25 * eyes + 0.15 * 0.7)
            if gsharp < 0.15:
                pscore *= 0.25
            cur = conn.execute(
                """INSERT INTO images(path, processed, width, height, series_id,
                   global_sharpness, exposure_score, print_score, taken_at, exif_time)
                   VALUES(?,1,800,600,?,?,?,?,?,1)""",
                (path, sid, gsharp, expo, pscore, 1700000000 + sid * 100 + k))
            iid = cur.lastrowid
            member_ids.append(iid)
            conn.execute(
                """INSERT INTO faces(image_id, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                   confidence, thumbnail, person_id, quality_score, eye_open)
                   VALUES(?,0,?,?,?,?,0.99,?,-1,?,?)""",
                (iid, *bbox, thumb, pscore, eyes))
            if pscore > best_score:
                best_score, best_iid = pscore, iid
        conn.execute("UPDATE images SET is_best_in_series=1 WHERE id=?", (best_iid,))
        conn.execute(
            "INSERT INTO series(id, frame_count, best_image_id) VALUES(?,?,?)",
            (sid, n, best_iid))

    conn.commit()
    print(f"seeded {db_file}: "
          f"{conn.execute('SELECT COUNT(*) c FROM persons').fetchone()['c']} persons, "
          f"{conn.execute('SELECT COUNT(*) c FROM faces').fetchone()['c']} faces, "
          f"{conn.execute('SELECT COUNT(*) c FROM series').fetchone()['c']} series")


if __name__ == "__main__":
    main()
