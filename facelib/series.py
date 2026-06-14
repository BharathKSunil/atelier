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
        key=lambda i: (items[i]["t"] is None,
                       items[i]["t"] if items[i]["t"] is not None else 0.0,
                       items[i]["id"]),
    )

    for k in range(1, len(order)):
        i, j = order[k - 1], order[k]
        ti, tj = items[i]["t"], items[j]["t"]
        cos = float(np.dot(items[i]["emb"], items[j]["emb"]))
        if ti is not None and tj is not None:
            if abs(tj - ti) <= time_gap_s and cos >= cos_threshold:
                union(i, j)
            elif cos >= embed_only_cos:
                union(i, j)
        else:
            if cos >= embed_only_cos:
                union(i, j)

    roots, result, next_id = {}, {}, 0
    for i in range(n):
        r = find(i)
        if r not in roots:
            roots[r] = next_id
            next_id += 1
        result[items[i]["id"]] = roots[r]
    return result
