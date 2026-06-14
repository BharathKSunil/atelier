# Project-Centric UI — Design Spec

**Date:** 2026-06-13
**Status:** Approved

## Goal

Turn the single-DB browse-only app into a project-centric workspace: create projects from the UI (each = its own DB), pick a folder via a native macOS dialog, watch indexing in a rich live Run console (progress + streaming log + live face grid), and inspect faces in detail (confidence, quality breakdown, source path, reveal in Finder).

## Decisions (from brainstorming)

- **Folder picker:** native macOS dialog (`osascript -e 'choose folder'`).
- **Run console:** live faces + per-phase progress + streaming log + error panel.
- **Home:** Projects dashboard (cards), opening a project reveals its People/Series/Run tabs.

## Architecture

### Projects model (multi-DB)
- Registry file `projects/registry.json`: `[{slug, name, source_folder, created_at}]`.
- One SQLite DB per project at `projects/<slug>.db` — reuses the existing `facelib/db.py` schema unchanged.
- Per-project run log at `projects/<slug>.log`.

### New modules
- `facelib/projects.py` — `list_projects() / create_project(name, folder) / get_project(slug) / delete_project(slug) / db_path(slug) / stats(slug)`. Slug = sanitized name, uniqued.
- `facelib/fsdialog.py` — `choose_folder() -> str|None` (osascript), `reveal(path)` (`open -R`). macOS-only; degrade gracefully if osascript missing.

### Runner (per project)
- `facelib/runner.py`: a `Runner` per slug (registry dict). Each enforces one run at a time.
- Status payload: `running, phase, phases_done, error, index_total, index_done, faces_found, errors, recent_face_ids[], log[]`.
- Tees output to `projects/<slug>.log`.

### Server routes (`04_server.py`)
- Global: `GET /api/projects`, `POST /api/projects` (create+start), `DELETE /api/projects/<slug>`, `POST /api/fs/choose`, `POST /api/fs/reveal`.
- Per-project: `/api/p/<slug>/stats`, `/persons`, `/persons/<pid>/faces`, `/persons/<pid>/rename`, `/series`, `/series/<sid>/images`, `/series/<sid>/best`, `/run` (start), `/run/status`, `/face/<fid>` (detail), `/thumb/<fid>`, `/image/<iid>`, `/image_thumb/<iid>`, `/export/<iid>`.
- Server CLI: `--projects-dir projects` (replaces `--db`). Phase scripts keep working standalone with `--db`.

### UI (vanilla JS, no build; split for focus)
- `web/api.js` — fetch helpers + project context.
- `web/dashboard.js` — project cards, new-project modal, folder picker, delete.
- `web/project.js` — workspace shell + People/Series tabs (port existing).
- `web/run.js` — live Run console (phases, progress, log, error panel, live face grid).
- `web/faces.js` — face detail modal (crop, confidence, quality bars, path, open/reveal).
- `web/main.js` — router (dashboard ↔ project), tab switching.

## Data flow

```
Dashboard --[+New: name+folder]--> POST /api/projects
  -> projects.create_project -> new projects/<slug>.db (init schema)
  -> runner[slug].start(folder) -> subprocess phases into that DB
  -> UI routes to Run console, polls /api/p/<slug>/run/status (~1s)
     renders phase/progress/counts/log + grid of recent_face_ids thumbs
On complete -> People/Series tabs read /api/p/<slug>/...
Face click -> /api/p/<slug>/face/<fid> -> detail modal
  Reveal -> POST /api/fs/reveal {path} -> open -R
```

## Error handling
- Folder not found / dialog cancelled → 400 with message, UI toast.
- Phase subprocess nonzero exit → captured in status.error + log, surfaced in Run console error panel; errored images already recorded `processed=2` (retry via existing `--retry-errors`).
- Delete project → confirm in UI; removes DB (+ wal/shm) + log + registry entry; never touches source photos.

## Out of scope (follow-ups)
- Changing the face-detection algorithm ("phase detection slightly off") — only surface confidence this iteration; tunable thresholds later.
- Pagination/lazy-load for very large clusters.
- Cross-platform folder dialog (mac-only for now).

## Testing
- `facelib/projects.py`: create/list/get/delete/slug-uniqueness/stats on a temp dir (no models).
- `facelib/fsdialog.py`: path-validation logic unit-testable; osascript call mocked/guarded.
- Existing pure-logic tests unaffected.
