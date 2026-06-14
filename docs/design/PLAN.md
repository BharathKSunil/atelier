> **Historical design note — superseded.** Documents an earlier architecture
> (the `facelib/` package, `01_index.py`…`04_server.py` scripts, MTCNN+FaceNet).
> The shipped tool is the `atelier` package with `atelier.pipeline.*` and an
> insightface/ArcFace stack. See the top-level `README.md` for current behavior.

# Photo Face Indexer — Implementation Plan

**Goal:** Browse a 20k+ local photo library by person, and pick the best frame of each burst for printing — no originals modified, fully local.

**Architecture:** A `facelib/` package holds all logic with heavy model imports kept lazy so the math stays unit-testable. Five CLI phases write to one SQLite DB: index → cluster persons → group series → score/pick → serve. A vanilla-JS SPA reads a Flask REST API.

**Tech Stack:** PyTorch (MPS) · facenet-pytorch (MTCNN + InceptionResnetV1) · DINOv2 (scene embedding) · HDBSCAN · MediaPipe FaceMesh · SQLite · Flask · vanilla JS.

---

## Two axes (the core design)

| | Use-case 1: by name | Use-case 2: best-of-series for print |
|---|---|---|
| Group by | identity (face embedding) | moment (scene embedding + EXIF time) |
| Cluster | HDBSCAN → `person_id` | union-find → `series_id` |
| "Best" | top face crop per person | top whole-frame `print_score` per series |
| Scoring | single face | group-aware: `min(eyes)` + global sharpness/exposure |

## Data flow

```
01_index   : photo -> images row + faces rows (embeddings, thumbs, full-res sharpness, exposure, global embed)
02_cluster : faces.embedding -> faces.person_id  + persons rows
02b_series : images.global_embedding + taken_at -> images.series_id + series rows
03_score   : faces thumbnails -> eye/smile/frontality -> quality_score, is_best
             images -> print_score, is_best_in_series, series.best_image_id
04_server  : SQLite -> REST + SPA
```

## Files

| File | Responsibility |
|---|---|
| `facelib/config.py` | constants/weights/thresholds (no heavy imports) |
| `facelib/db.py` | schema + connection |
| `facelib/imaging.py` | load/resize, EXIF + mtime fallback |
| `facelib/quality.py` | pure math: sharpness, exposure, EAR, frontality, smile, print_score |
| `facelib/series.py` | union-find burst grouping |
| `facelib/models.py` | lazy MTCNN / InceptionResnetV1 / DINOv2 loaders |
| `01_index.py` … `04_server.py` | the five phases |
| `web/` | SPA (People + Series tabs) |
| `tests/` | pure-logic unit tests (no models) |

## Print score (group-aware)

```
print = 0.40·global_sharpness          (full-res Laplacian variance, normalized)
      + 0.20·exposure                  (peak at mean 128, penalize clipping)
      + 0.25·min(eye_open over faces)   ← one blink ruins a group print
      + 0.15·mean(smile,frontality over faces)
if global_sharpness < 0.15: print *= 0.25   (motion blur => not printable)
```

## Series grouping

EXIF-time-sorted; union temporally adjacent frames when `gap ≤ 10s AND cosine ≥ 0.88`,
or `cosine ≥ 0.92` regardless of time. No-EXIF frames (PNG) merge only on the tight 0.92.

## Key decisions

- **Sharpness on full-res, in Phase 1** while the file is already open — avoids re-reading 400 GB and keeps the motion-blur signal intact (downscaling destroys it).
- **Phase 3 reads only the DB** (stored thumbnails) — no second pass over originals.
- **Resumable** Phase 1 via `images.processed` (0/1/2); errors recorded, never fatal.
- **Lazy heavy imports** so `quality`/`series`/`db`/`imaging` test with numpy+Pillow only.

## Status

All phases + UI + tests implemented. Pure-logic tests pass without models.
Running the model phases requires `pip install -r requirements.txt` (torch/mediapipe).

## Possible follow-ups

- Face alignment before embedding (accuracy) · lazy-loading for very large clusters ·
  constraint propagation to merge a person split across extreme lighting ·
  composition scoring (rule-of-thirds) in print_score · per-image thumbnail cache table.
