"""Per-project tunables: spec for the UI, persistence, and runner flag mapping.

Each knob declares which phase it feeds and which re-run it requires:
  reindex  -> detection gates (full pipeline)
  recluster-> identity clustering (cluster + fast rescore)
  regroup  -> series/bursts (series + fast rescore)
"""

from . import config, projects

# key, label, group, min, max, step, default, affects, phase, flag, help
SPEC = [
    (
        "det_threshold",
        "Detection confidence",
        "Detection",
        0.30,
        0.85,
        0.05,
        config.FACE_DET_THRESHOLD,
        "reindex",
        "index",
        "--det-threshold",
        "How sure the face detector must be to keep a face. Higher = fewer false positives "
        "(hair, jewelry, fabric tagged as people) but may drop real faces in hard light. Lower "
        "catches more faces but lets in junk that pollutes your people groups.",
    ),
    (
        "min_px",
        "Min face size (px)",
        "Detection",
        16,
        96,
        4,
        config.FACE_MIN_PX,
        "reindex",
        "index",
        "--min-px",
        "Smallest face to keep, measured in the analysis image. Raise to ignore tiny background "
        "guests; lower to catch distant faces (which embed less reliably).",
    ),
    (
        "min_sharpness",
        "Min sharpness",
        "Detection",
        0.0,
        0.30,
        0.01,
        config.FACE_MIN_SHARPNESS,
        "reindex",
        "index",
        "--min-sharpness",
        "Drops out-of-focus face blobs below this sharpness. Higher keeps only crisp faces; too "
        "high also drops soft-focus portraits.",
    ),
    (
        "min_frontality",
        "Min frontality (drops profiles)",
        "Detection",
        0.0,
        0.7,
        0.05,
        config.FACE_MIN_FRONTALITY,
        "reindex",
        "index",
        "--min-frontality",
        "How straight-on a face must be. Higher drops side-profiles and ears, whose embeddings "
        "cluster badly and create duplicate people; lower keeps profiles at the cost of messier groups.",
    ),
    (
        "min_cluster_size",
        "Min cluster size",
        "Clustering",
        2,
        30,
        1,
        config.HDBSCAN_MIN_CLUSTER,
        "recluster",
        "cluster",
        "--min-cluster-size",
        "Fewest faces needed to form a person. Higher = fewer, cleaner people (rare faces fall to "
        "'ungrouped'); lower = more people but more duplicates and fragments.",
    ),
    (
        "min_samples",
        "Min samples",
        "Clustering",
        1,
        15,
        1,
        config.HDBSCAN_MIN_SAMPLES,
        "recluster",
        "cluster",
        "--min-samples",
        "How conservative clustering is about noise. Higher = tighter cores with more faces left "
        "ungrouped; lower = more inclusive (and occasionally over-merged) people.",
    ),
    (
        "selection_epsilon",
        "Merge tolerance (ε)",
        "Clustering",
        0.0,
        0.6,
        0.02,
        config.HDBSCAN_SELECTION_EPSILON,
        "recluster",
        "cluster",
        "--selection-epsilon",
        "Merges density-similar fragments of one person split across lighting/pose. Raise to "
        "combine such fragments; too high starts merging different people.",
    ),
    (
        "merge_cosine",
        "Centroid-merge cosine (0=off)",
        "Clustering",
        0.0,
        0.99,
        0.01,
        config.CLUSTER_MERGE_COSINE,
        "recluster",
        "cluster",
        "--merge-cosine",
        "After clustering, merges two people whose average face embeddings are at least this alike. "
        "Lower merges more aggressively (fewer duplicates, but risks wrong merges); 0 disables it.",
    ),
    (
        "time_gap",
        "Burst time gap (s)",
        "Series",
        1,
        120,
        1,
        config.SERIES_TIME_GAP_S,
        "regroup",
        "series",
        "--time-gap",
        "Photos shot within this many seconds can belong to the same burst. Larger groups looser "
        "sequences together; smaller keeps only rapid-fire frames in a burst.",
    ),
    (
        "series_cos",
        "Burst similarity",
        "Series",
        0.50,
        0.99,
        0.01,
        config.SERIES_COS_THRESHOLD,
        "regroup",
        "series",
        "--cos",
        "How visually alike frames must be to join a burst (within the time gap). Higher = tighter "
        "bursts of near-identical shots; lower groups looser variations of a moment.",
    ),
    (
        "embed_cos",
        "No-timestamp similarity",
        "Series",
        0.50,
        0.99,
        0.01,
        config.SERIES_EMBED_ONLY_COS,
        "regroup",
        "series",
        "--embed-cos",
        "Same as burst similarity, but for photos with no timestamp (e.g. PNG) — they're grouped "
        "into bursts purely by how alike they look.",
    ),
]

_INT_KEYS = {"min_px", "min_cluster_size", "min_samples"}
PHASES_FOR = {
    "reindex": ["index", "cluster", "series", "score"],
    "recluster": ["cluster", "score"],
    "regroup": ["series", "score"],
}


def spec_json():
    return [
        {"key": k, "label": l, "group": g, "min": mn, "max": mx, "step": st, "default": d, "affects": a, "help": hlp}
        for (k, l, g, mn, mx, st, d, a, _ph, _fl, hlp) in SPEC
    ]


def defaults():
    return {k: d for (k, _l, _g, _mn, _mx, _st, d, _a, _ph, _fl, _hlp) in SPEC}


def load(projects_dir, slug):
    vals = defaults()
    p = projects.get_project(projects_dir, slug) or {}
    vals.update(p.get("params") or {})
    return vals


def save(projects_dir, slug, params):
    ranges = {k: (mn, mx) for (k, _l, _g, mn, mx, _st, _d, _a, _ph, _fl, _hlp) in SPEC}
    clean = {}
    for k, v in (params or {}).items():
        if k not in ranges:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        mn, mx = ranges[k]
        clean[k] = max(mn, min(mx, fv))
    projects.set_params(projects_dir, slug, clean)
    return load(projects_dir, slug)


def phase_flags(values):
    """{phase_name: [flag, value, ...]} for runner.start(flags=...)."""
    out = {}
    for k, _l, _g, _mn, _mx, _st, _d, _a, ph, fl, _hlp in SPEC:
        if k in values:
            v = values[k]
            sval = str(int(round(v))) if k in _INT_KEYS else f"{float(v):g}"
            out.setdefault(ph, []).extend([fl, sval])
    return out
