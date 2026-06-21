# Atelier — Backlog

Working list of bugs + features. Larger roadmaps live in
[`docs/audit/review-scale-audit.md`](audit/review-scale-audit.md) (scale/usability/feature-gap audit)
and [`docs/design/scoring-taxonomy.md`](design/scoring-taxonomy.md) (quality metrics & scoring).

**Order of work:** bugs ✅ → metrics taxonomy P0 ✅ → features easiest → hardest (F1 → F4 → F2 → F3).

**Done so far:** B1 + B2 fixed (`runner.py`). Metrics taxonomy **P0 shipped** — every photo is now analysed on every metric (stored as columns in `images`), with context-aware picks (group eyes-strict, moment soft-on-eyes, everyone/smile/candid/aesthetic), plain-language tags ("7/8 eyes open"), and 6 ratable feedback rows. See [`design/scoring-taxonomy.md`](design/scoring-taxonomy.md) §5 for the remaining P1 (MediaPipe extractions: per-eye blink, genuine smile, head-pose, gaze, skin-tone exposure, subject-vs-bg sharpness) and P2 (learned aesthetic head trained on `pick_feedback`).

---

## 🐞 Bugs

### B1 — Run logs not visible after a server restart
**Symptom:** "Run logs per project not captured/stored?"
**Root cause:** logs *are* written to disk (`runs_dir/<run_id>.log`, mirrored to `run.log`, recorded in the `runs` table), but the live `/run/log` endpoint reads only the in-memory ring buffer (`Runner.log`), which is empty after a restart — so the console looks blank. (`runner.py:92` `log_lines`, `runner.py:198` `_open_log`.)
**Fix:** on runner creation, seed the in-memory log + `_seq` from the last run's on-disk log file so `/run/log` replays it. **Status: fixing now.**

### B2 — Run status resets on re-launch (only faces shown)
**Symptom:** after restarting the server, the Run screen shows no phase/progress/completion — just the face count/grid.
**Root cause:** `get_runner()` builds a fresh `Runner` with `state` all reset; `status()` returns that blank state plus live DB counts (faces/index totals), so only the DB-derived "faces" survive. The `runs` table is never read back into `state`. (`runner.py:56` initial state, `runner.py:383` `get_runner`.)
**Fix:** hydrate `state` from the most recent `runs` row on creation (status → phases_done/finished/error), so a finished run shows "Complete ✓" after a restart. **Status: fixing now.** *(Note: `runs` doesn't store the source folder, so the "Source:" line stays blank after a restart — add a `folder` column later if wanted.)*

---

## Bucket / print-list unification  ✅ DONE
- **Print list is just a bucket** — db v11 migrates `picks(pick_type='print')` into a default "Print list" bucket (`buckets.role`/`is_default`). `star`/`star_many`/`prints`/`is_print` all operate on the project **default bucket**.
- **Spacebar → the default bucket** (any bucket can be the default; `POST /buckets/<id>/set-default`).
- **Inspector "In buckets · where it lands"** — chips show membership + click to add/remove; default marked ★. Star button + frame pill use the default bucket's name.
- **Per-project config** — the new-project dialog seeds starter buckets + picks the default; the Buckets tab can re-point the default (default can't be deleted).
- **Feedback is a collapsed `<details>` accordion**.
- New endpoints: `/buckets/<id>/set-default`, `/export-images`; `/buckets` returns `role`/`is_default`. Tests in `test_server.py`.

## ✨ Features (easiest → hardest)

### F1 — "Select all images" on the person view  ✅ DONE
**Select all / Clear** in the person detail ticks all loaded faces; the selection drives **Bucket N selected… / Export N selected… / Split out (N)**, or whole-person when nothing's ticked. New `POST /api/p/<slug>/export-images` (image ids → copy, `_safe_dest`-guarded). (`people.js`, `server.py`.)

### F4 — Re-run project (destroy + fresh run)  ✅ DONE
**Decision: destroy everything (clean slate).** "Start over…" button on the Run screen → strong destructive confirm → `POST /api/p/<slug>/rerun-fresh` deletes the whole DB (+ WAL/SHM), recreates it empty, and re-runs the full pipeline from scratch. Originals untouched. (`server.py`, `run.js`, regression test in `test_server.py`.)

### F2 — Face-filtered review: solo / with-others  ✅ DONE
From a person, **Review solo** (this person is the only face) and **Review with others** (appears with others) open the **same Review/cull desk** scoped to that flat set. New `GET /api/p/<slug>/review-set?person&mode=solo|group`; cull.js gained a filter mode (one-shot `setReviewFilter` from People) with an "‹ exit" chip, position counter, ←→ stepping, and star/bucket/zoom/face-chips — picks/feedback/sort hidden (series-only). (`server.py`, `cull.js`, `people.js`.)

### F3 — Face-filtered review: duet / multi  ✅ DONE
Select 2+ people on the People grid → **Review together** (every selected person present, others allowed) or **Review only these** (exactly the selected people, nobody else identified). Opens the same cull desk. `review-set` extended with `?persons=…&mode=together|only`; `people.js` select-bar actions; `cull.js` filter mode carries a person list. Tests in `test_server.py`.

**All backlog features (F1–F4) + the bucket/print-list unification are done.**

---

## Pointers to the larger roadmaps
- **Scale / usability / feature gaps** (RAW ingest, reject flag, zoom, XMP export, resume, sort/filter): `docs/audit/review-scale-audit.md` §5 roadmap.
- **Scoring & new pick types** (soft eyes model, joy/moment/cohesion picks, learned aesthetic): `docs/design/scoring-taxonomy.md` §5 roadmap.
