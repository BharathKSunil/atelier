# Contributing to Atelier

Thanks for helping out. Atelier is a local-only macOS photo-culling tool; PRs and issues are welcome.

## Setup

Use **Python 3.11 or 3.12** (the face/ML wheels don't build on newer versions yet).

```bash
make install-dev   # light test deps only — pure-logic modules, fast, no torch/mediapipe
# or
make install       # full ML stack (torch, insightface, mediapipe, hdbscan, DINOv2)
# or, manually:
pip install -e ".[dev]"
```

`install-dev` is enough to run the unit tests and lint. You only need the full
stack (`make install`) when you're touching the index/recognition path or want
to run the pipeline end to end.

## Checks

```bash
ruff check . && pytest -q
```

Both run in CI (`.github/workflows/ci.yml`). Please make sure they pass locally
before opening a PR.

## Conventions

- **Heavy imports stay lazy.** torch, insightface, mediapipe, and friends are
  imported *inside* the functions that need them — never at module top level.
  This keeps the pure modules (`quality`, `series`, `db`, `imaging`, `config`)
  importable with only numpy/Pillow, so the math stays unit-testable without
  pulling in gigabytes of deps. Don't add a top-level `import torch`.
- **Lint:** ruff, line-length **120**. Run `ruff check .` (or `ruff check --fix .`).
- **Tests** live in `tests/`. Prefer testing pure logic; if a test would need
  models or a GPU, gate it or mock the heavy import.
- **Comments** explain *why*, not *what*. Skip docstrings on obvious functions.

## Security model — please don't break it

Atelier is **single-user, loopback-only by design**:

- The server binds `127.0.0.1` only and is **unauthenticated**. That's
  intentional — it's a local tool, not a service.
- A CSRF token guards state-changing requests.

Please **do not** add a `--host 0.0.0.0` flag, bind to a public interface, or
otherwise make the server reachable from the network "for convenience". If you
have a real multi-user use case, open an issue to discuss it first — it's a
design change, not a patch.

## Commits & PRs

- Conventional-ish commit messages (`feat:`, `fix:`, `docs:`, …) are appreciated
  but **not required** — a clear summary line is fine.
- Keep PRs focused. Describe what changed and how you tested it.
- Include before/after screenshots for any web-UI change.

That's it. Open an issue if anything here is unclear.
