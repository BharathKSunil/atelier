# Photo Face Indexer

Browse a large local photo library by **person** and pick the **best frame of each burst for printing** — without renaming, moving, or modifying any original file. Everything stays local (SQLite, no cloud).

Two use-cases:
1. **Group by name** — detect + cluster faces, label people, browse their photos.
2. **Best of a series, for print** — group near-identical shots (bursts), score whole-frame print quality (group-aware: one blink disqualifies a frame), pick the single best to print.

## Pipeline

| Phase | Script | Does | Time (20k imgs, M1 Max) |
|---|---|---|---|
| 1 Index | `01_index.py` | MTCNN faces → 512-d identity embed + DINOv2 384-d scene embed; full-res sharpness/exposure | ~2–4 h (I/O bound), resumable |
| 2 Persons | `02_cluster_persons.py` | HDBSCAN over face embeddings → `person_id` | minutes |
| 2b Series | `02b_group_series.py` | EXIF time + scene embedding → `series_id` (bursts) | minutes |
| 3 Score | `03_score.py` | MediaPipe landmarks → eyes/smile/frontality; best face per person + best frame per series | ~30–60 min |
| 4 Browse | `04_server.py` | Flask + web UI at localhost:5050 | instant |

## Quickstart (make)

The web UI is **project-centric** — create projects, pick folders, and run the pipeline from the browser. Each project gets its own database.

```bash
make install     # venv (mise) + full pipeline deps (torch, mediapipe, ...)
make start       # web server -> http://localhost:5050
make open        # open the dashboard
#   then: + New Project -> Choose Folder (native picker) -> it indexes live
make demo        # or: seed a synthetic demo project to explore first
make stop
```

CLI pipeline (still available, scriptable):

```bash
make pipeline PHOTOS=/path/to/photos DB=faces.db   # index -> cluster -> series -> score
make reindex  PHOTOS=/path DB=faces.db             # retry images that errored
make cluster  DB=faces.db MIN_CLUSTER=2            # re-cluster (small libraries)
```

Common vars: `PROJECTS_DIR=projects`, `PORT=5050`, `PHOTOS=/path`, `DB=`. Server lifecycle: `start` / `stop` / `restart` / `status` / `logs` / `serve` (foreground). Cleanup: `clean` / `clean-all`. `make help` lists everything.

## Setup (manual)

```bash
cd wedding-photos
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # full pipeline (torch, mediapipe, ...)
python -c "import torch; print('MPS:', torch.backends.mps.is_available())"   # want: True
```

> Apple Silicon: if a model hits an unsupported MPS op, run with
> `PYTORCH_ENABLE_MPS_FALLBACK=1 python 01_index.py ...` to fall back to CPU for that op.

## Run

```bash
python 01_index.py --photos /path/to/photos --db faces.db   # resumable — safe to Ctrl-C and rerun
python 02_cluster_persons.py --db faces.db
python 02b_group_series.py --db faces.db
python 03_score.py --db faces.db
python 04_server.py --db faces.db --port 5050               # open http://localhost:5050
```

Tunables (cluster sizes, series thresholds, print weights) live in `facelib/config.py`.
Re-cluster persons or regroup series anytime by re-running phase 2 / 2b — the index (phase 1) is untouched.

## Web UI

- **Dashboard** — one card per project (name, source folder, counts, live status). **+ New Project** → name + **Choose Folder…** (native macOS picker) → creates a DB and starts indexing.
- **Run console** — per-phase steps, progress bar, live counts (images / faces / errors), streaming log, error panel, and a **live grid of faces** appearing as they're detected.
- **People tab** — paginated, infinite-scroll sidebar (handles thousands of people). Rename inline. Tick faces to **Merge into…** another person or **Split out** to a new one — manual merges/splits survive re-clustering (anchored on stable face ids, re-applied after HDBSCAN). Click a face → **detail modal**: crop, detection confidence, quality bars, source path, Open original + Reveal in Finder.
- **Series tab** — paginated, **collapsed rows** (best-frame thumbnail + count); expand to lazy-load the frame strip. Each frame carries **per-criterion pick pills** — `group` / `aesthetic` / `candid` — toggle any independently. Auto picks are derived from scores; your manual picks override them and **survive regroup + rescore**. Export copies the original into `./print_exports/`.

### Scale & quality (20k images)

- **Pagination + lazy loading + infinite scroll** everywhere; series rows collapse and load frames on demand — no more rendering 972 series at once.
- **Persisted image thumbnails** (`images.thumbnail`) — the browse path never re-decodes a 20 MB original.
- **Non-destructive pipeline:** re-runs preserve renames (carried by face-membership overlap) and manual merges/splits/picks. Schema evolves via `PRAGMA user_version` migrations applied on connect.
- **Monotone sharpness** (`1-exp(-var/k)`) replaces the cap that saturated every in-focus photo to 1.0.
- **Over-split levers** (off by default; tune in `facelib/config.py`): `HDBSCAN_SELECTION_EPSILON`, `CLUSTER_MERGE_COSINE` (centroid-cosine merge post-pass). `make cluster MIN_CLUSTER=…` to sweep.

### Face engine (detection + recognition)

Default backend is **insightface** — RetinaFace detection + ArcFace embeddings (`buffalo_l`, auto-downloads). This fixes the two failure modes of the old MTCNN+FaceNet stack:
- **False positives** (jewelry, hands, hair, skin tagged as people) — rejected by the detector confidence gate `FACE_DET_THRESHOLD` (0.60).
- **Junk/duplicate clusters** — ArcFace separates identities far better (same-person cosine ~0.98 vs different ~0.15; FaceNet gave ~0.51), so HDBSCAN over-splits and false-merges much less.

Index-time gates in `facelib/config.py`: `FACE_DET_THRESHOLD`, `FACE_MIN_PX`, `FACE_MIN_SHARPNESS`. Set `FACE_BACKEND="mtcnn"` to fall back.

> **Switching backend requires a full re-index** — embeddings live in a different space:
> ```bash
> make reindex PHOTOS=/path/to/photos DB=projects/<slug>.db   # or delete the DB and re-run the pipeline
> make cluster DB=projects/<slug>.db
> ```

### Storage

Projects live under **`~/.atelier/<project>/`** (override with `ATELIER_HOME`), one folder per project:

```
~/.atelier/
  registry.json
  <slug>/db.sqlite        # the project database
  <slug>/run.log          # last pipeline run log
```

On first launch the server **auto-migrates** an old flat `./projects/` layout into the nested one (WAL-checkpointed copy, idempotent). `make start` and the server default to `~/.atelier`; override with `make start PROJECTS_DIR=/path` or `ATELIER_HOME=/path`.

### Performance (Apple Silicon)

insightface runs on **CoreML** when available (auto-detected; falls back to CPU / CUDA) — measured ~2.7× faster detection and ~16× faster recognition on M-series vs CPU. Don't mix CPU- and CoreML-indexed embeddings in one project DB; re-index a project after changing `INSIGHTFACE_PROVIDERS`.

### Dev

```bash
pip install -e ".[dev]"   # editable install (pyproject.toml)
ruff check . && pytest -q  # lint + tests (also run in CI: .github/workflows/ci.yml)
```

### Deferred (documented follow-ups)

- 5-point face alignment before embedding (needs re-index + opencv; A/B since vggface2 trained on unaligned crops).
- Externalizing thumbnails to disk (DB-size diet at 100k faces).
- Per-project tunables surfaced in the UI; a learned aesthetic model (current `aesthetic` pick is a colorfulness+exposure+sharpness heuristic, not a trained model).

## Architecture notes

- `facelib/` holds all logic. Heavy imports (torch, facenet, mediapipe) are **lazy** — pure modules (`quality`, `series`, `db`, `imaging`) import with numpy/Pillow only, so the math is unit-testable without GBs of deps.
- **I/O bound, not GPU bound:** reading ~400 GB once dominates. External drives are the real bottleneck.
- **Sharpness measured on full-res** (Phase 1, while the file is open) — downscaled sharpness is unreliable for detecting motion blur.
- **Print score is group-aware:** `min(eye_open)` over all faces, so one person blinking sinks a group shot. Formula + weights in `facelib/config.py` and `facelib/quality.py`.
- File formats: **JPEG + PNG** (Pillow native). PNG has no EXIF time → falls back to file mtime and series-grouping relies on the scene embedding for those.

## Tests

Pure-logic tests need no models:

```bash
pip install -r requirements-dev.txt
pytest -q
```
