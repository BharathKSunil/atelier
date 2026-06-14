# Photo Library Face Indexer — Requirements & Solution Design

## Context

A personal photo library of **20,000+ images** (~20MB each, ~400GB total) stored in **nested folders** on an **Apple MacBook Pro M1 Max**. The goal is to browse and organise photos by the people in them — without renaming, moving, or modifying any original files.

---

## Requirements

### R1 — Index by Face
Scan the entire nested photo library and produce an index that maps each detected face back to its source image. No files should be renamed or moved. The index must be queryable so that individual images can be loaded and displayed on demand.

### R2 — Group Similar Faces
Automatically group faces of the same person together into clusters. Each cluster represents one person. The grouping must work without any prior labelling or manual input.

### R3 — Best Image Selection *(optional but desirable)*
Within each person's cluster, automatically identify the single best photo using objective quality signals:

| Signal | Description |
|---|---|
| Eyes open | Detect whether eyes are open or closed |
| Sharpness | How in-focus the face crop is |
| Brightness | Penalise over- or under-exposed faces |
| Frontality | Prefer straight-on faces over profiles |
| Smile | Minor positive signal for open-mouth smiles |

### R4 — Browsable Web UI
A locally-hosted web application to browse persons, view all their photos, rename them, and open any photo at full resolution in a lightbox.

### R5 — Storage
All metadata (file paths, bounding boxes, embeddings, cluster assignments, quality scores) stored in a **SQLite** database. No cloud dependency.

### R6 — Performance on M1
The pipeline must be practical to run on the M1 Max. Apple Silicon GPU acceleration should be used wherever possible. The indexer must be **resumable** — safe to interrupt and restart without reprocessing already-indexed images.

---

## Hardware & Environment

| Property | Detail |
|---|---|
| Machine | Apple MacBook Pro M1 Max |
| RAM | 32GB unified memory |
| OS | macOS |
| Photo count | 20,000+ images |
| Image size | ~20MB each (~400GB total) |
| Folder structure | Nested directories |
| GPU backend | Apple MPS (Metal Performance Shaders) via PyTorch |

---

## Solution Design

### Technology Stack

| Role | Library | Reason |
|---|---|---|
| Face detection | `facenet-pytorch` → MTCNN | Proven accuracy, included in FaceNet package |
| Face embedding | `InceptionResnetV1` (vggface2 weights) | 512-dim embeddings, strong recognition across pose & lighting |
| GPU acceleration | PyTorch MPS backend | Native Apple Silicon GPU; significant speedup over CPU |
| Clustering | `hdbscan` | No need to guess cluster count; handles noise/outliers natively; scales to 100k+ faces |
| Quality scoring | `mediapipe` Face Mesh + OpenCV | Provides 468-point facial landmarks for EAR, frontality, smile |
| Database | `sqlite3` (stdlib) | Zero-dependency, local, queryable, fast for this scale |
| Web server | `flask` | Lightweight, serves both the REST API and the static frontend |
| Frontend | Vanilla JS + HTML/CSS | No build step, runs immediately |

### Why HDBSCAN over Agglomerative Clustering
The article this project is based on used Agglomerative Clustering with a manually tuned cluster count. At 20k images with multiple faces per image, the face count could reach 50k–150k. HDBSCAN avoids the need to pre-specify the number of clusters, handles noise points (partial faces, non-faces) by labelling them `-1` rather than forcing them into a cluster, and is significantly faster at this scale via parallelised distance computation.

---

## Pipeline Phases

```
Phase 1 — Index       (01_index_faces.py)
  Input  : Nested photo folders
  Process: MTCNN detection → InceptionResnetV1 embedding (MPS) → face thumbnail crop
  Output : SQLite: images table + faces table (embeddings, bboxes, thumbnails)
  Time   : ~2–4 hours for 20k images on M1 (resumable)

Phase 2 — Cluster     (02_cluster_faces.py)
  Input  : All 512-dim embeddings from SQLite
  Process: L2 normalise → HDBSCAN
  Output : person_id written back to each face row
  Time   : Minutes

Phase 3 — Quality     (03_score_quality.py)
  Input  : Face thumbnail BLOBs from SQLite
  Process: MediaPipe landmarks → EAR + frontality + smile + sharpness + brightness
  Output : quality_score per face; is_best=1 for top face per person
  Time   : ~30–60 minutes for 50k faces

Phase 4 — Browse      (04_server.py + web/index.html)
  Input  : SQLite database
  Process: Flask REST API + single-page web app
  Output : Local web UI at http://localhost:5000
  Time   : Instant
```

---

## Database Schema

### `images`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | |
| path | TEXT UNIQUE | Absolute path to original file |
| file_size | INTEGER | Bytes |
| width, height | INTEGER | Image dimensions |
| processed | INTEGER | 0=pending, 1=done, 2=error |
| error_msg | TEXT | Set on error |

### `faces`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | |
| image_id | INTEGER FK | → images.id |
| face_index | INTEGER | 0-based index within image |
| bbox_x1/y1/x2/y2 | REAL | Bounding box in original image coordinates |
| confidence | REAL | MTCNN detection confidence |
| embedding | BLOB | 512 × float32 (2048 bytes) |
| thumbnail | BLOB | JPEG bytes of padded face crop (≤50KB) |
| person_id | INTEGER | Cluster label from HDBSCAN; -1 = noise |
| quality_score | REAL | Composite quality score in [0, 1] |
| is_best | INTEGER | 1 = highest quality face for this person |

### `persons`
| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Matches person_id in faces |
| display_name | TEXT | User-assigned name (set via web UI) |
| notes | TEXT | Free-form notes |

---

## Quality Scoring Formula

```
quality = 0.35 × sharpness
        + 0.20 × brightness
        + 0.25 × eye_openness
        + 0.15 × frontality
        + 0.05 × smile
```

| Signal | Method | Range |
|---|---|---|
| Sharpness | Laplacian variance of face crop (cap at 500) | [0, 1] |
| Brightness | Peak at mean=128; penalise <50 or >200 | [0, 1] |
| Eye openness | Eye Aspect Ratio from MediaPipe landmarks | [0, 1] |
| Frontality | Nose horizontal offset vs cheek midpoint | [0, 1] |
| Smile | Mouth height/width ratio | [0, 1] |

---

## Web UI Features

- **Persons sidebar** — all detected people, sorted by photo count or name
- **Person detail view** — grid or list of all their photos, sorted by quality score
- **Best image badge** — highest-scoring photo highlighted in each person's gallery
- **Rename** — click to assign a real name to any person; persisted in SQLite
- **Full-resolution lightbox** — click any face to open the original ~20MB image
- **Filename search** — filter across all indexed images by path substring
- **Stats bar** — live count of persons, faces, and images in the database

---

## Installation

```bash
# Install Python dependencies
pip install facenet-pytorch hdbscan mediapipe flask \
            scikit-learn numpy pillow tqdm torch torchvision
```

```bash
# Verify MPS is available
python -c "import torch; print(torch.backends.mps.is_available())"
# Should print: True
```

---

## Usage

```bash
# Step 1 — Index (resumable, ~2-4 hours)
python 01_index_faces.py --photos /Volumes/Photos --db faces.db

# Step 2 — Cluster (minutes)
python 02_cluster_faces.py --db faces.db

# Step 3 — Score quality (~30-60 min)
python 03_score_quality.py --db faces.db

# Step 4 — Browse
python 04_server.py --db faces.db --port 5000
# Open http://localhost:5000
```

---

## Known Limitations & Future Work

| Item | Note |
|---|---|
| HEIC support | Pillow may need `pillow-heif` plugin for native HEIC/HEIF files |
| Same person → multiple clusters | Can happen with extreme lighting changes; solvable with constraint propagation in a future phase |
| Noise faces | Partial/blurry faces get `person_id = -1`; browsable but not grouped |
| Small clusters / small libraries | HDBSCAN needs density to form clusters: a person in fewer than `min_cluster_size` photos is marked noise, and on very small sets (≪100 faces) it may label everything noise. This is expected at the 50k+ face target scale; for small libraries lower it via `make cluster MIN_CLUSTER=2`. |
| Re-clustering | Changing `min_cluster_size` re-runs Phase 2; Phases 3–4 are unaffected |
| Face alignment | Skipped for speed; adding alignment before embedding would improve accuracy |
| Pagination | Web UI loads up to 200 faces per person; very large clusters may need lazy loading |
