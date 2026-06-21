# Atelier — Backlog

Working list of bugs + features. Larger roadmaps live in
[`docs/audit/review-scale-audit.md`](audit/review-scale-audit.md) (scale/usability/feature-gap audit)
and [`docs/design/scoring-taxonomy.md`](design/scoring-taxonomy.md) (quality metrics & scoring).

**Order of work:** bugs ✅ → metrics taxonomy P0 ✅ → features easiest → hardest (F1 → F4 → F2 → F3).

**Done so far:** B1 + B2 fixed (`runner.py`). Metrics taxonomy **P0 shipped** — every photo is now analysed on every metric (stored as columns in `images`), with context-aware picks (group eyes-strict, moment soft-on-eyes, everyone/smile/candid/aesthetic), plain-language tags ("7/8 eyes open"), and 6 ratable feedback rows.

**Metrics taxonomy P1 (extractions) shipped** — the score phase now reads MediaPipe **blendshapes** + the **head-pose transform** from one FaceLandmarker pass (db v12 face columns): independent per-eye blink (`eye_left`/`eye_right`, robust `eye_open`), head-pose Euler (`yaw`/`pitch`/`roll` → pose-based frontality, roll-blind), gaze-at-camera (`gaze` + a "N/N eye contact" tag), and a Duchenne genuine-smile signal (`genuine_smile`). All degrade gracefully to the EAR/geometry signals when blendshapes are unavailable. Verified end-to-end on a real face. Also **fixed a migration-ordering bug** (v11 was applied before v10, skipping v10's columns on upgrading DBs) + added a column self-heal.

**Metrics taxonomy P1 (light / colour / focus) shipped** — db v13 + pure-numpy scorers over the stored thumbnails (no originals re-read, except background sharpness which is measured in the index pass): highlight/shadow clipping, global contrast, white-balance cast (measured only on low-sat mid-luma pixels so golden-hour warmth doesn't false-flag), hue scatter, skin-tone/subject exposure, Dutch-tilt (hard-gated on a dominant edge axis), and subject-vs-background sharpness (`bokeh`) from a faces-masked background Laplacian. The inspector surfaces the bad ones as flags (blown / crushed / cast / tilted / dim subject) plus `bokeh` as a positive. Verified end-to-end (pure-fn unit tests + a monkeypatched score run + a real-image sanity pass).

**Metrics taxonomy P2/P3 (scene / focus / dup) shipped** — db v14: golden-hour warmth, rim/back-light, background clutter, mirror symmetry, structure-tensor motion-blur (anisotropy, only flagged when sharpness is also low), per-face grimace + talking from the already-extracted blendshapes, and within-burst near-duplicate (`redundancy`) from the stored DINOv2 embeddings. Inspector flags: motion blur / busy background / grimace / talking / near-duplicate (warn) + golden hour (good). Pure-fn unit tests + score wiring test + real-image sanity.

**Deliberately NOT shipped** (would emit garbage without more): lead-room and mutual-gaze need a *calibrated* yaw sign (MediaPipe's transform doesn't give a reliable one); leading-lines (Hough) and subject-region motion-blur false-positive too often on real scenes to be worth it.

**Learned pick head (scaffold) shipped** — db v15 + `atelier/learning.py` + `python -m atelier.pipeline.learn` (`mise run learn`). A pure-numpy logistic RankNet over the per-image signals + DINOv2 embedding, warm-started from the heuristic (weight 1.0 on the pick's own score column) and L2-regularized toward it, trained on within-burst preference PAIRS mined from `pick_feedback` + bucket keeps. Below `LEARN_MIN_PAIRS` (30) it refuses and keeps the heuristic. Predictions land in `images.learned_score`; the model persists in `learned_models`. The picker uses the learned score for a pick **only** once that pick has a trained model (`group`==`print`), so it's a no-op until there's feedback. Tested: learns an embedding signal the warm-start can't separate, the degrade floor, persistence, and the picker hand-off.

**This needs the photographer's real feedback to actually help** — it's wired and verified on synthetic labels, but won't change picks until `pick_feedback`/bucket keeps accumulate on a real project, then `mise run learn`.

**Still genuinely open in §5:** per-pick learned heads (one model trained at a time today), the NIMA-on-DINOv2 aesthetic head as a standalone, and the new-extract signals noted above. See [`design/scoring-taxonomy.md`](design/scoring-taxonomy.md) §5.

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
