"""Group images into 'series' (same moment / burst). Pure numpy union-find.

Signal = EXIF time blocking + global-embedding cosine (use-case 2).
Items with no timestamp (t=None) merge only on a tighter embed-only cosine.
"""

import numpy as np


def group_series(items, time_gap_s, cos_threshold, embed_only_cos):
    """items: list of {"id": int, "t": float|None, "emb": np.ndarray (L2-normalized)}.

    Returns {image_id: series_id}. Singletons get their own series_id.
    Only temporally adjacent frames are compared — exactly burst behavior.
    """
    n = len(items)
    if n == 0:
        return {}

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # time-sorted; None timestamps sort to the end, stable by id
    order = sorted(
        range(n),
        key=lambda i: (items[i]["t"] is None, items[i]["t"] if items[i]["t"] is not None else 0.0, items[i]["id"]),
    )

    # Timestamped frames: union temporally adjacent neighbors (burst behavior).
    for k in range(1, len(order)):
        i, j = order[k - 1], order[k]
        ti, tj = items[i]["t"], items[j]["t"]
        if ti is None or tj is None:
            continue  # timestamp-less frames handled by the O(m^2) pass below
        cos = float(np.dot(items[i]["emb"], items[j]["emb"]))
        if abs(tj - ti) <= time_gap_s and cos >= cos_threshold or cos >= embed_only_cos:
            union(i, j)

    # Timestamp-less frames (e.g. PNG) share no temporal order, so adjacency by id
    # is meaningless — two identical shots can be non-adjacent and an unrelated shot
    # can sort between them. Compare every pair and merge on the tighter embed cosine.
    none_idx = [i for i in range(n) if items[i]["t"] is None]
    for a in range(len(none_idx)):
        ia = none_idx[a]
        for b in range(a + 1, len(none_idx)):
            ib = none_idx[b]
            if float(np.dot(items[ia]["emb"], items[ib]["emb"])) >= embed_only_cos:
                union(ia, ib)

    roots, result, next_id = {}, {}, 0
    for i in range(n):
        r = find(i)
        if r not in roots:
            roots[r] = next_id
            next_id += 1
        result[items[i]["id"]] = roots[r]
    return result
