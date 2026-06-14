#!/usr/bin/env python3
"""Phase 2 — Cluster faces into persons (use-case 1: group by name).

L2-normalize 512-d face embeddings, then HDBSCAN. Non-destructive:
  - display_name / notes are carried forward by face-membership overlap (Jaccard),
    so renames survive re-clustering.
  - manual merge/split/reassign overrides (atelier.overrides) are re-applied after.
person_id == -1 means noise (browsable but ungrouped).
"""
import argparse
import sqlite3
from collections import defaultdict

import numpy as np

from atelier import config, db, overrides
from atelier.errors import DatabaseError


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="faces.db")
    ap.add_argument("--min-cluster-size", type=int, default=config.HDBSCAN_MIN_CLUSTER)
    ap.add_argument("--min-samples", type=int, default=config.HDBSCAN_MIN_SAMPLES)
    ap.add_argument("--selection-epsilon", type=float, default=config.HDBSCAN_SELECTION_EPSILON)
    ap.add_argument("--merge-cosine", type=float, default=config.CLUSTER_MERGE_COSINE,
                    help="merge clusters whose centroids exceed this cosine (0 disables)")
    args = ap.parse_args()

    try:
        conn = db.connect(args.db)
        rows = list(conn.execute("SELECT id, embedding FROM faces WHERE embedding IS NOT NULL"))
    except sqlite3.Error as e:
        raise DatabaseError(f"failed reading faces from {args.db}: {e}") from e
    if not rows:
        print("no faces — run 01_index.py first")
        return

    ids = [r["id"] for r in rows]
    X = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)

    import hdbscan
    # euclidean on L2-normalized vectors is monotonic with cosine distance, so
    # this is effectively cosine clustering.
    labels = hdbscan.HDBSCAN(
        min_cluster_size=args.min_cluster_size,
        min_samples=args.min_samples,
        metric="euclidean",
        cluster_selection_epsilon=args.selection_epsilon,
    ).fit_predict(X)
    labels = labels.astype(int)

    # optional centroid-cosine merge post-pass: collapse fragments of the same
    # person split across lighting/pose (addresses over-split).
    if args.merge_cosine and args.merge_cosine > 0:
        labels = _merge_by_centroid(X, labels, args.merge_cosine)

    # capture prior membership + names BEFORE overwriting, to inherit custom names
    prior = {}
    for r in conn.execute(
            """SELECT f.id fid, f.person_id pid, p.display_name dn, p.notes no
               FROM faces f JOIN persons p ON p.id=f.person_id WHERE f.person_id>=0"""):
        d = prior.setdefault(r["pid"], {"name": r["dn"], "notes": r["no"], "faces": set()})
        d["faces"].add(r["fid"])

    try:
        conn.executemany("UPDATE faces SET person_id=? WHERE id=?",
                         [(int(l), fid) for fid, l in zip(ids, labels)])

        new_members = defaultdict(set)
        for fid, l in zip(ids, labels):
            if l >= 0:
                new_members[int(l)].add(fid)

        conn.execute("DELETE FROM persons")
        for lab, members in new_members.items():
            name, notes, best_ov = f"Person {lab}", None, 0.0
            for d in prior.values():
                if not d["name"] or d["name"].startswith("Person "):
                    continue
                inter = len(members & d["faces"])
                if not inter:
                    continue
                ov = inter / len(members | d["faces"])
                if ov > best_ov:
                    best_ov, name, notes = ov, d["name"], d["notes"]
            conn.execute("INSERT OR IGNORE INTO persons(id, display_name, notes) VALUES(?,?,?)",
                         (lab, name, notes))
        conn.commit()

        overrides.apply_overrides(conn)   # re-impose manual merges/splits
        # drop person rows left empty after a merge collapsed faces onto one cluster
        conn.execute("DELETE FROM persons WHERE id NOT IN "
                     "(SELECT DISTINCT person_id FROM faces WHERE person_id >= 0)")
        conn.commit()

        n_persons = conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
    except sqlite3.Error as e:
        raise DatabaseError(f"failed writing clusters to {args.db}: {e}") from e
    n_noise = int((labels == -1).sum())
    print(f"{n_persons} persons over {len(ids)} faces ({n_noise} noise)")
    print(f"silhouette: {_silhouette(X, labels)}")


def _silhouette(X, labels):
    """Mean silhouette over non-noise points (sampled to <=5000), or 'n/a'.

    Higher is better; helps operators tune min_cluster_size/min_samples.
    """
    try:
        from sklearn.metrics import silhouette_score

        mask = labels >= 0
        Xc, lc = X[mask], labels[mask]
        if len(set(lc.tolist())) < 2:
            return "n/a"
        if len(lc) > 5000:
            idx = np.random.default_rng(0).choice(len(lc), 5000, replace=False)
            Xc, lc = Xc[idx], lc[idx]
        return f"{silhouette_score(Xc, lc):.3f}"
    except Exception:  # noqa: BLE001
        return "n/a"


def _merge_by_centroid(X, labels, cos_threshold):
    """Union clusters whose L2-normalized centroids have cosine >= threshold.

    The pairwise cosine is one BLAS matmul (C @ C.T) over the centroids; the union
    loop then touches only the above-threshold pairs. The old O(clusters^2) Python
    double-loop of np.dot calls hung at a few thousand clusters.
    """
    uniq = sorted(set(int(l) for l in labels) - {-1})
    if len(uniq) < 2:
        return labels
    C = np.stack([X[labels == lab].mean(axis=0) for lab in uniq])
    C = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
    sim = C @ C.T                                   # full pairwise cosine, vectorized
    parent = {lab: lab for lab in uniq}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ai, bj = np.triu_indices(len(uniq), k=1)         # upper triangle only (excl. diagonal)
    hits = np.nonzero(sim[ai, bj] >= cos_threshold)[0]
    for p in hits:
        parent[find(uniq[ai[p]])] = find(uniq[bj[p]])
    return np.array([find(int(l)) if l >= 0 else -1 for l in labels])


if __name__ == "__main__":
    main()
