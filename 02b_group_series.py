#!/usr/bin/env python3
"""Phase 2b — Group images into series / bursts (use-case 2: same moment).

Signal = EXIF time blocking + DINOv2 global-embedding cosine. Images without
reliable EXIF time (PNG -> mtime fallback) merge only on a tighter embed cosine.
"""
import argparse
from collections import defaultdict

import numpy as np

from facelib import config, db, series


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="faces.db")
    ap.add_argument("--time-gap", type=float, default=config.SERIES_TIME_GAP_S)
    ap.add_argument("--cos", type=float, default=config.SERIES_COS_THRESHOLD)
    ap.add_argument("--embed-cos", type=float, default=config.SERIES_EMBED_ONLY_COS)
    args = ap.parse_args()

    conn = db.connect(args.db)
    rows = list(conn.execute(
        """SELECT id, taken_at, exif_time, global_embedding FROM images
           WHERE processed=1 AND global_embedding IS NOT NULL"""))
    if not rows:
        print("no indexed images — run 01_index.py first")
        return

    items = []
    for r in rows:
        emb = np.frombuffer(r["global_embedding"], dtype=np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        items.append({
            "id": r["id"],
            "t": r["taken_at"] if r["exif_time"] else None,
            "emb": emb,
        })

    mapping = series.group_series(items, args.time_gap, args.cos, args.embed_cos)

    conn.execute("DELETE FROM series")
    conn.executemany("UPDATE images SET series_id=? WHERE id=?",
                     [(sid, iid) for iid, sid in mapping.items()])

    members = defaultdict(list)
    for iid, sid in mapping.items():
        members[sid].append(iid)
    tmap = {r["id"]: r["taken_at"] for r in rows}
    for sid, ids in members.items():
        ts = [tmap[i] for i in ids if tmap[i] is not None]
        conn.execute(
            "INSERT OR REPLACE INTO series(id, frame_count, time_start, time_end) VALUES(?,?,?,?)",
            (sid, len(ids), min(ts) if ts else None, max(ts) if ts else None))
    conn.commit()

    multi = sum(1 for ids in members.values() if len(ids) > 1)
    print(f"{len(members)} series ({multi} with >1 frame) over {len(items)} images")


if __name__ == "__main__":
    main()
