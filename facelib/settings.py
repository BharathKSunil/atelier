"""Per-project tunables: spec for the UI, persistence, and runner flag mapping.

Each knob declares which phase it feeds and which re-run it requires:
  reindex  -> detection gates (full pipeline)
  recluster-> identity clustering (cluster + fast rescore)
  regroup  -> series/bursts (series + fast rescore)
"""
from . import config, projects

# key, label, group, min, max, step, default, affects, phase, flag
SPEC = [
    ("det_threshold", "Detection confidence", "Detection", 0.30, 0.85, 0.05,
     config.FACE_DET_THRESHOLD, "reindex", "index", "--det-threshold"),
    ("min_px", "Min face size (px)", "Detection", 16, 96, 4,
     config.FACE_MIN_PX, "reindex", "index", "--min-px"),
    ("min_sharpness", "Min sharpness", "Detection", 0.0, 0.30, 0.01,
     config.FACE_MIN_SHARPNESS, "reindex", "index", "--min-sharpness"),
    ("min_frontality", "Min frontality (drops profiles)", "Detection", 0.0, 0.7, 0.05,
     config.FACE_MIN_FRONTALITY, "reindex", "index", "--min-frontality"),

    ("min_cluster_size", "Min cluster size", "Clustering", 2, 30, 1,
     config.HDBSCAN_MIN_CLUSTER, "recluster", "cluster", "--min-cluster-size"),
    ("min_samples", "Min samples", "Clustering", 1, 15, 1,
     config.HDBSCAN_MIN_SAMPLES, "recluster", "cluster", "--min-samples"),
    ("selection_epsilon", "Merge tolerance (ε)", "Clustering", 0.0, 0.6, 0.02,
     config.HDBSCAN_SELECTION_EPSILON, "recluster", "cluster", "--selection-epsilon"),
    ("merge_cosine", "Centroid-merge cosine (0=off)", "Clustering", 0.0, 0.99, 0.01,
     config.CLUSTER_MERGE_COSINE, "recluster", "cluster", "--merge-cosine"),

    ("time_gap", "Burst time gap (s)", "Series", 1, 120, 1,
     config.SERIES_TIME_GAP_S, "regroup", "series", "--time-gap"),
    ("series_cos", "Burst similarity", "Series", 0.50, 0.99, 0.01,
     config.SERIES_COS_THRESHOLD, "regroup", "series", "--cos"),
    ("embed_cos", "No-timestamp similarity", "Series", 0.50, 0.99, 0.01,
     config.SERIES_EMBED_ONLY_COS, "regroup", "series", "--embed-cos"),
]

_INT_KEYS = {"min_px", "min_cluster_size", "min_samples"}
PHASES_FOR = {
    "reindex": ["index", "cluster", "series", "score"],
    "recluster": ["cluster", "score"],
    "regroup": ["series", "score"],
}


def spec_json():
    return [{"key": k, "label": l, "group": g, "min": mn, "max": mx, "step": st,
             "default": d, "affects": a}
            for (k, l, g, mn, mx, st, d, a, _ph, _fl) in SPEC]


def defaults():
    return {k: d for (k, _l, _g, _mn, _mx, _st, d, _a, _ph, _fl) in SPEC}


def load(projects_dir, slug):
    vals = defaults()
    p = projects.get_project(projects_dir, slug) or {}
    vals.update(p.get("params") or {})
    return vals


def save(projects_dir, slug, params):
    ranges = {k: (mn, mx) for (k, _l, _g, mn, mx, _st, _d, _a, _ph, _fl) in SPEC}
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
    for (k, _l, _g, _mn, _mx, _st, _d, _a, ph, fl) in SPEC:
        if k in values:
            v = values[k]
            sval = str(int(round(v))) if k in _INT_KEYS else f"{float(v):g}"
            out.setdefault(ph, []).extend([fl, sval])
    return out
