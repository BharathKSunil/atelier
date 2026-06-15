# Atelier — Behaviour Specifications (BDD)

These `.feature` files are **behaviour specs written in Gherkin** that describe the
shipped Atelier feature set — a local-only macOS photo-culling tool (a Flask REST
API plus a vanilla-JS ES-module SPA, with one SQLite database per project under
`~/.atelier/<slug>/`).

They document **what the product actually does** — endpoints and their status
codes, UI flows (clicks, key presses), validation failures, security rejections,
empty states, and persistence across re-runs — from the **user's / API client's
perspective**, not from implementation internals.

> These specs document behaviour. They are **not wired to a test runner** — there
> are no step definitions and nothing executes them. Treat them as the executable-
> _looking_, authoritative description of how each feature is meant to behave.

## Conventions

- Each file opens with `Feature:` and a short narrative — *As a `<role>` I want
  `<goal>` so that `<benefit>`*.
- `Background:` holds shared setup; `Scenario:` describes one distinct behaviour;
  `Scenario Outline:` + `Examples:` cover parameterised behaviours.
- Steps follow **Given / When / Then** (with **And** / **But**) and consistent
  phrasing, written as user actions and HTTP calls + responses.
- Both **happy paths and error/edge cases** are covered (validation, security
  rejections, cancellation, empty states, persistence across a pipeline re-run).
- Scenarios are **tagged** where useful: `@api`, `@ui`, `@security`,
  `@persistence`.

## The feature files

| File | Title | Scenarios | What it covers |
| --- | --- | --: | --- |
| [`projects-and-dashboard.feature`](./projects-and-dashboard.feature) | Projects and dashboard | 22 | Creating a project from a folder (name + folder required, slug assignment, own DB, indexing kicks off), the New Project modal and native folder picker, dashboard cards (cover mosaic, people/bursts/photos stats, indexing vs N-faces pill), empty states, delete (confirm, 409 while running, DB-only removal), per-project isolation, and the token + local-host guards. |
| [`pipeline-run-and-run-screen.feature`](./pipeline-run-and-run-screen.feature) | Pipeline run and the Run screen | 28 | The four sequential phases (index → cluster → series → score), per-stage cards and timing, index progress, Stop/cancel, second-run 409, auto-opening logs with captured traceback on failure, SSE state/logs persisting across a mid-run reload, stall-watchdog termination, server-restart reconciliation, and settings-triggered partial re-runs. |
| [`face-detection-and-indexing.feature`](./face-detection-and-indexing.feature) | Face detection and indexing (phase 1) | 22 | EXIF-upright loading, the confidence / min-pixel / sharpness / frontality gates, the MediaPipe second-opinion and box/keypoint plausibility checks for borderline detections, resumable + retryable indexing, per-image and per-face thumbnails, JPEG/PNG metadata handling, idempotent re-index, and CLI overrides of the `FACE_*` thresholds. |
| [`people-clustering-and-identity-edits.feature`](./people-clustering-and-identity-edits.feature) | People — clustering, browse, and manual identity edits | 31 | HDBSCAN clustering with centroid merge, ungrouped noise faces, rename / merge / split / reject, "Not this person" (extract or remove + visually-similar review), edits surviving a re-cluster via stable face-id anchors, the paginated people grid + name search, live refresh of an open person, and the validation + security guards. |
| [`review-cull.feature`](./review-cull.feature) | Review / cull: bursts, best frame, picks, print list, keyboard flow | 31 | Multi-frame bursts only (ordered by frame count), the recommended hero frame, auto multi-criteria picks (group/candid/aesthetic) with image-anchored manual overrides and toggle-off, starring keepers (single, range via shift-click, recommended), a frozen filmstrip order, fullscreen, the full keyboard flow, stale-slug/burst guards, the empty state, and validation + security. |
| [`print-list.feature`](./print-list.feature) | Print list of starred keepers | 22 | The starred-keepers list with a selected-count header, 60-per-page infinite scroll with limit/offset clamping and ordering, removing via unstar, opening frames in the lightbox, exporting all copies into the default per-project folder (skipping missing sources, rejecting out-of-bounds dests), the empty + load-error states, persistence across a re-run, and export/unstar security. |
| [`buckets.feature`](./buckets.feature) | Buckets — user-defined photo collections | 31 | Buckets as collections separate from the print list — create (auto colour, default sort), rename/recolour, delete (keeps photos), many-buckets-per-photo, Review number-key + chip toggles with coloured dots, adding selected people's photos by face (deduped union), the styled bucket picker, browse + remove + export with destination confinement, and membership persisting across re-runs. |
| [`per-project-settings.feature`](./per-project-settings.feature) | Per-project settings (tuning knobs) | 22 | GET settings (spec + values grouped Detection/Clustering/Series), per-knob help balloons and slider/number sync, "Save only" (PUT, no re-run), clamping and ignoring of unknown/non-numeric keys, the gated Save & re-index / re-cluster / re-group flows that navigate to Run, the correct phase subset per `affects`, persistence across reload, unknown-slug 404, in-progress 409, the load-failure state, and int/float flag formatting. |
| [`security-model-and-safe-export.feature`](./security-model-and-safe-export.feature) | Security model and safe export | 23 | Loopback-only binding, non-local Host and cross-origin Origin rejection (403), the per-process `X-Atelier-Token` required on mutating requests (GETs allowed without it), token injection into `index.html`, export-destination confinement to allowed roots with realpath traversal/symlink resolution, safe default destinations, the native-picker availability gating and AppleScript-injection guard, the off-macOS typing fallback, and union/dedup export with containment enforced. |
| [`face-inspector-and-media.feature`](./face-inspector-and-media.feature) | Face inspector and media serving | 30 | The face-detail modal (crop + confidence/quality + sharpness/eyes/smile/frontality bars, embedding/thumbnail stripped from the JSON, source path, unknown-fid 404), Open original → lightbox, Reveal in Finder, the "Not this person" entry points, and the media endpoints — face thumb, per-image thumbnail with on-the-fly decode fallback + 1-day cache, and full original — with their 404 paths. |
| [`app-shell.feature`](./app-shell.feature) | App shell — routing, network resilience, notifications, modal a11y | 40 | Cross-cutting UX: hash routing (`#/`, `#/p/<slug>/<mode>`, unknown-mode→review), the offline/online banner, the 15s request-abort timeout, success vs sticky-error toasts, modal focus-trap with focus restoration, the single global Escape (topmost overlay only), and the multi-image lightbox gallery (arrows/buttons, single-image, backdrop/Escape close). |
| [`run-history-and-api-details.feature`](./run-history-and-api-details.feature) | Run history and remaining API-level behaviours | 34 | Lower-level API contracts: the `runs` history list + restart reconciliation, durable per-run log retrieval (`/runs/<id>/log`), per-person and single-image export with count/containment, the `buckets/for-images` membership map driving the Review dots, bucket-browse pagination + clamping, and the dashboard cover-selection (print-score ordering + fallback) rule. |

**Total: 12 feature files, 370 scenarios.**
