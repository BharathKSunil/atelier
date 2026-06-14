# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-15

Initial public release.

### Added

- **Face indexing** — SCRFD detection + ArcFace embeddings (insightface
  `buffalo_l`) with index-time quality gates (detector confidence, minimum
  pixel size, sharpness) and EXIF-upright crops.
- **Person clustering** — HDBSCAN over ArcFace embeddings with a centroid-cosine
  merge post-pass to reduce over-splitting.
- **Burst / series grouping** — EXIF capture time + DINOv2 scene embeddings group
  near-identical shots into series.
- **Multi-criteria best-frame picks** — independent `group`, `aesthetic`, and
  `candid` picks per series, with group-aware scoring (one blink sinks a group
  shot).
- **Project-centric web UI** — Flask + vanilla-JS SPA; create projects, pick
  folders, and run the pipeline from the browser with a live run console.
- **Manual overrides that survive re-clustering** — merge / split / rename /
  reject / export overrides are anchored on stable face ids and re-applied after
  HDBSCAN, regroup, and rescore.
- **Per-project SQLite** with `PRAGMA user_version` schema migrations applied on
  connect, stored under `~/.atelier/<slug>/`.
- **macOS CoreML acceleration** — insightface runs on CoreML when available
  (auto-detected, falls back to CPU/CUDA).

[Unreleased]: https://github.com/bharathksunil/atelier/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bharathksunil/atelier/releases/tag/v0.1.0
