# Atelier — Photographic Quality Metrics & Scoring Taxonomy

> Research + design proposal (multi-agent, June 2026): 74 metrics catalogued across 6 categories,
> 62 feasibility-checked against Atelier's actual signals. Goal: expand scoring beyond
> eyes/smile and make the model soft enough that **a great frame can beat strict both-eyes-open**.
> Line refs are guidance against the current `quality.py` / `config.py` / `server.py`.

## 1. The core shift: from a hard eyes-MIN gate to a soft weighted model

### What's actually wrong today

The complaint "a hard both-eyes-open gate is too strict" is half right, and the half that's wrong matters for where we cut.

`quality._eyes_aggregate` (quality.py:127) is **already** face-count-aware: it returns `mean` for a single face, a blend for 2–3 faces, and a pure `min(eye_open)` **only for groups of 4+**. So the brittle cliff is narrower than stated — but it is real for exactly the high-value case (a 12-person family/group frame where one back-row guest blinks).

The other defects are more pervasive:

- **`smile` and `frontality` are flattened to one mean.** `print_score` (quality.py:140) collapses them to `expr = mean((smile+frontality)/2)` — so one frowner among eleven happy faces is invisible. The MIN gate is on eyes only; expression has *no* straggler sensitivity at all.
- **The sharpness "disqualifier" is a step discontinuity, not a hard cull.** `print_score`/`candid_score` apply `score *= PRINT_BLUR_PENALTY (0.25)` when `global_sharp < PRINT_DISQUALIFY_SHARP (0.15)` (quality.py:152, config.py:90). It's a ×0.25 cliff at exactly 0.15 — a once-in-a-lifetime frame at 0.149 gets slammed; at 0.151 it sails through. The product-owner pain ("a good frame should still rank") is really this cliff, plus the eyes MIN, not a literal hard gate.
- **`smile` is mouth-aperture, not a smile.** `quality.smile` (quality.py:87) is `lip_gap / mouth_width` — it scores a yawn or mid-speech open mouth as a big smile and a closed-lip genuine smile as ~0. Every "expression" term inherits this.

### The formula change

**Current** (quality.py:140):
```
print_score = 0.40*global_sharp + 0.20*exposure
            + 0.25*_eyes_aggregate(eyes)        # min() for 4+ faces
            + 0.15*mean((smile+frontality)/2)
if global_sharp < 0.15: score *= 0.25           # step cliff
```

**Proposed** — soft cohesion aggregation + continuous blur floor, all over columns already in the DB:
```
# per-face engagement, area-weighted so a tiny back-row face can't dominate
w_i        = sqrt(face_area_i) / Σ sqrt(face_area_j)      # bbox already stored, orig-px
eyes_term  = Σ w_i * eye_open_i                            # weighted mean, NOT min
frac_eyes  = mean(eye_open_i  >= 0.5)
frac_smile = mean(smile_i     >= 0.35)                     # smile = mouth-open proxy for now
frac_front = mean(frontality_i>= 0.50)
stragglers = count(face below ANY threshold)
group_term = w_e*frac_eyes + w_s*frac_smile + w_f*frac_front
           - STRAGGLER_PEN * min(stragglers, CAP)

print_score = 0.40*global_sharp + 0.20*exposure + PRINT_W_GROUP*group_term
blur_mult   = sigmoid((global_sharp - 0.15) / 0.04)        # ~0.25 well below, ~1 above 0.25
print_score *= blur_mult                                   # continuous, replaces the ×0.25 step
```

Three concrete edits, **zero new extraction** (all inputs — `eye_open`, `smile`, `frontality`, `bbox`, `global_sharpness_raw` — are persisted):

1. Replace the `min`-for-4+ branch of `_eyes_aggregate` with the area-weighted mean + straggler penalty.
2. Replace the `expr` mean with the three fractions so one frowner is *visible*.
3. Replace the step disqualifier with the `sigmoid` floor in both `print_score` and `candid_score`.

Net effect: one blink in a 12-person frame drops the score by ~1/N instead of zeroing it; two stragglers still demote it; a slightly-soft moment loses a little instead of being cliff-penalized — so a strong moment/expression/composition frame **can** outscore a technically-clean-but-dull one. New weights/thresholds go in the existing `PRINT_W_*` block in config.py.

### How the pick-feedback table feeds learned weighting

The hand-tuned weights above are the **warm start**. The `pick_feedback` table (db v9) already collects, per auto pick: `verdict` (good/bad), `better_image_id` (an explicit pairwise "this frame should have won"), and `note`, joined with the scores in `/feedback/export` (server.py:812). Plus implicit positives from `buckets`/`bucket_items` and `source='manual'` pick overrides.

Training recipe (the same plumbing for every learned head in §5):
- **Pairwise labels within a series:** `better_image_id > auto_image_id`; `verdict='good'` auto pick > its losing siblings.
- **Features:** `[global_embedding (384-d) | aggregated face signals (eye_open, smile, frontality, face_sharpness, face_count) | exposure | sharpness | the new composition/light terms]`.
- **Model:** a thin RankNet/hinge correction layer over today's linear scores (warm-started = current weights), so it degrades gracefully below ~100 labels. Retrain offline, write per-image scores back in `pipeline/score.py` into the same `_SCORE_COL` columns the read-time picker already consumes (server.py:705). One model conditioned on `pick_type`, or one head per pick.

---

## 2. The metric catalog

Ratings are **feasibility-corrected**. Derivable: **now** = read-time math over stored columns; **small-extract** = new code in the index/score pass (often a one-flag MediaPipe change + a column), no new model; **new-model/new-extract** = new pixel-touching extractor, learned head, or signed-pose persistence + reindex; **needs-exif** = capture metadata Atelier doesn't store.

### 2A. Face & Expression

| Metric (term / aka) | Definition | Signal | Derivable | Plug-in | Audience | Priority |
|---|---|---|---|---|---|---|
| Per-eye openness (blink vs squint) / "nobody mid-blink" | Independent L/R EAR + a blink-vs-squint discriminator so a laugh-squint isn't penalized like a blink | 478-pt mesh EAR per eye; iris ring **ellipticity** 469↔471/474↔476; **better:** `eyeBlinkL/R` blendshape | now (EAR) / small-extract (robust) | soft gate + score term: replace eyes-MIN with per-face `no_blink` | everyone | **P0** |
| Genuine (Duchenne) vs forced smile / "real vs say-cheese" | Co-activation of mouth + cheek-raise/eye-crinkle vs mouth-only | `mouthSmileL/R + cheekSquintL/R + eyeSquintL/R` blendshapes (one flag) | small-extract | score term + new `joy` pick; store new col, don't overwrite `smile` | both | **P0** |
| Even/consistent group expression / "is EVERYONE smiling" | Fraction of faces simultaneously eyes-open, smiling, facing | per-face `eye_open`/`smile`/`frontality` stored | **now** | the §1 fix: fraction-good + straggler-penalty replaces blunt MIN | everyone | **P0** |
| Group cohesion / everyone engaged | `engagement_i = eye_open_i * facing_i`, soft-aggregated | `eye_open`, `frontality` (head dir, not gaze) | **now** | soft replacement for `_eyes_aggregate` MIN; display "7/8 engaged" | everyone | **P0** |
| Looking-at-camera (head-pose yaw/pitch/roll) | Decompose orientation; today's `frontality` is unsigned yaw, roll/pitch-blind | `output_facial_transformation_matrixes=True` → 4×4 → Euler | small-extract | group rewards frontal, candid rewards mild off-axis | both | **P0** |
| Grimace / awkward transient | Half-blink, sneer, brow-furrow, asymmetry at a bad instant | `browDown/noseSneer/mouthFrown` blendshapes; half-EAR fallback now | small-extract (fallback now) | per-face soft dampener on all picks | both | P1 |
| Mouth-open / talking / mid-speech | Open mouth from speech, not smile | inner-lip 13/14/78/308 (now); `jawOpen` vs `mouthSmile` (robust) | small-extract (geom now) | `smile_corrected = smile*(1-talking)` | both | P1 |
| Gaze direction / eye-contact | Iris offset vs eye-corner midpoint | iris 468–477 in mesh; gate on eye-width ≥~6px | small-extract | eye-contact bonus / averted-gaze soft penalty | both | P1 |
| Eyes-on-each-other (mutual gaze) | Two gaze/yaw vectors converging | signed yaw (not stored today) + iris + bbox | new-model | new `connection` pick, no frontality reward | both | P1 |
| Critical focus on the eyes | Eye-region Laplacian vs whole-crop | full-res crop **+** landmarks together (index.py) | new-extract | heavy soft term in portrait pick | both | P0 (new-extract) |
| Catchlight (eye sparkle) | Specular blob in iris | iris landmarks + bright blob; gate on face size | small-extract | tiny positive portrait tie-breaker | pro | P3 |

### 2B. Composition

| Metric (term / aka) | Definition | Signal | Derivable | Plug-in | Audience | Priority |
|---|---|---|---|---|---|---|
| Crop safety / "nobody sliced by the edge" | Important face touching/cut at a frame edge | bbox vs W,H — bbox **clamped** at store, so overshoot lost | small-extract | soft gate ~×0.7 on edge-touch | both | **P0** |
| Headroom | Scalp-referenced space above topmost head | topmost-face `bbox_y1`/height + scalp offset | now | ~0.15 in composition_score | both | P1 |
| Rule of thirds | Distance of subject anchor to nearest third intersection | face bbox center / W,H (upright) | now | ~0.20 soft term (normalizer 0.393, never a gate) | both | P1 |
| Subject size / scale | Frac of frame the subject fills | largest/summed bbox area / (W·H) | now | **router**: tiny subject → lean on aesthetic | everyone | P1 |
| Horizon level / Dutch tilt | Dominant near-horizontal line angle | numpy Sobel gradient-orientation histogram | small-extract | soft ×0.9 floor; gate on low angular spread | both | P1 |
| Negative space / clutter | Background edge-density outside masked faces | thumbnail gray, masked mean-\|grad\| | small-extract | within-series tiebreaker | both | P2 |
| Symmetry (intentional) | L/R mirror similarity + subject centered | normalized mirror-MAE + centered | small-extract | rescues centered heroes vs thirds | pro | P2 |
| Gaze/lead room | Space on the side the subject faces | needs **signed** look dir | new-extract | ~0.10, active for non-frontal | pro | P2 |
| Leading lines | Lines converging on subject | Hough on 1536px `small` | new-extract | +0.05 additive bonus only | pro | P3 |

### 2C. Light, exposure & color

| Metric (term / aka) | Definition | Signal | Derivable | Plug-in | Audience | Priority |
|---|---|---|---|---|---|---|
| Correct overall exposure | Tonal mass in usable mid-range | `exposure_score` stored & weighted | now | keep; down-weight once skin-tone exposure exists | everyone | **P0** |
| Skin-tone / subject exposure | Brightness of the **face** vs whole frame | face thumb L + skin mask (YCbCr/oval) | small-extract | high-weight term + soft penalty for people | both | **P0** |
| Highlight clipping / blown | Near-white area fraction | `(L>=250).mean()` on thumbnail | small-extract | graduated penalty; near-hard gate on blown skin | both | **P0** |
| Shadow crush / blocked | Crushed-black fraction, face-weighted | `(L<=4).mean()` recomputed | small-extract | soft penalty escalated on crushed face | both | **P0** |
| Global contrast | std of luminance on [0,1] | `L.std()/255` on thumbnail | now | new ~0.10 aesthetic term | both | P1 |
| White balance / color cast | Residual cast on low-sat mid-luma pixels | opponent R-G, (R+G)/2-B | now | penalty for green/magenta cast | both | P1 |
| Color harmony / colorfulness | Vividness tempered by hue coherence | `colorfulness` + circular-variance of hue | now | temper the 0.40 color weight | both | P1 |
| Golden-hour warmth | Warm directional light | warm-axis (R−B)/(R+B) now | small-extract / new-model (reliable pick) | warmth aesthetic term now | both | P2 |
| Rim / back light | Bright halo outside head silhouette | image-thumbnail ring vs interior | small-extract | dramatic-light term + backlit rescue gate | pro | P2 |

### 2D. Focus, sharpness & depth

| Metric (term / aka) | Definition | Signal | Derivable | Plug-in | Audience | Priority |
|---|---|---|---|---|---|---|
| Overall image sharpness | Whole-frame acutance | `global_sharpness_raw` stored | now | existing 0.40 term; **step-cliff → sigmoid floor** | both | **P0** |
| Per-face sharpness | Crop acutance, per face | `face_sharpness_raw` stored | now | existing term; **area-weight** the group aggregation | both | P1 |
| Subject-vs-bg sharpness (bokeh) | Subject sharp / background soft | mask faces out of `gray_full`, store `bg_sharpness_raw` | small-extract | portrait term; confidence-gated, never a gate | both | P1 |
| Focus-missed / back-focus | Sharp plane not on subject | new `bg_sharpness_raw` extract | small-extract | soft penalty + "focus missed" filter | both | P1 |
| Motion blur (camera shake) | Uniform directional smear | structure-tensor anisotropy on `gray_full` | new-extract | typed soft penalty distinct from defocus | both | P2 |
| Subject motion blur | Localized smear, sharp bg | per-region anisotropy | new-extract | **positive** term in action/candid pick | both | P2 |

### 2E. Moment & storytelling

| Metric (term / aka) | Definition | Signal | Derivable | Plug-in | Audience | Priority |
|---|---|---|---|---|---|---|
| Decisive moment | Soft fusion of expression+composition+sharp, **no** eyes-MIN gate | all stored (gaze proxied by frontality+eye_open) | small-extract | new `moment` pick — the central tension fix | both | **P0** |
| Emotional intensity / joy | Magnitude × genuineness of positive emotion | `mouthSmile + cheekSquint`-weighted | small-extract | feeds moment/peak/candid | both | **P0** |
| Group cohesion / engaged | (see 2A) | stored scalars | now | replaces eyes-MIN | everyone | **P0** |
| Peak action / peak-of-motion | Apex of a burst arc | per-series expression extremum + bbox displacement | new-extract | new `peak` pick | both | P0 (new-extract) |
| Candid vs posed | Authentic vs lineup | frontality variance + arrangement regularity | small-extract | refine `candid`, add `posed` pick | both | P1 |
| Interaction / connection | People engaged with each other | proximity now; convergence needs signed yaw | new-extract | `connection` pick; proximity-only v1 ships now | both | P1 |
| Burst-novelty / non-redundant | New moment vs near-dup | DINOv2 cosine (existing) | now | MMR re-rank over picks | everyone | P1 |
| Tears / crying | Happy-cry keeper | weak from current signals | new-model | low-weight bonus once head exists | both | P2 |
| Gesture / hands | Toast, ring reveal, clap | **no body/hand model** | new-model | future term | both | P3 |

### 2F. Aesthetic & technical (ML-scorable)

| Metric (term / aka) | Definition | Signal | Derivable | Plug-in | Audience | Priority |
|---|---|---|---|---|---|---|
| Learned aesthetic (NIMA on DINOv2) | Trained wall-worthiness from your taste | stored 384-d `global_embedding` | new-model | drop-in replace `aesthetic_proxy` | both | **P0** |
| Technical quality (NR-IQA) | Sharp+exposed+clean, content-blind | `squash(sharp)*exposure` | small-extract | `tq_gate` replaces the step disqualifier | both | **P0** |
| Embedding pick regressor | Learns your keeps from feedback | `pick_feedback` (v9) + buckets + manual | new-model | produces the `_SCORE_COL` numbers | both | **P0** |
| Wall-worthy / print-worthiness | Headline keeper rating | composite of learned heads + face/moment | new-model | new `wall_worthy` pick | both | P1 |
| Distracting elements | Edge-cut person, photobomb, hotspot | edge-touch **now**; hotspot needs col | small-extract | soft penalty + explainable cull filters | both | P1 |
| Near-duplicate redundancy | Surface best of a redundant cluster | DINOv2 cosine | now | non-destructive "hide near-dups" toggle | everyone | P1 |
| Saliency / subject prominence | One clear hero vs scattered | `dominance = max_face/Σfaces` | small-extract (people now) | wall_worthy term + tiebreaker | both | P2 |

---

## 3. Proposed pick_types

Today: `PICK_TYPES = ["group", "aesthetic", "candid"]` with `_SCORE_COL` mapping each to one stored per-image column (config.py:69, server.py:705). Each pick is a read-time `max()` over one column. **Adding a pick = one `PICK_TYPES` entry + one `_SCORE_COL` entry + one column written in `pipeline/score.py`.** The picker, manual-override, and feedback loop then support it for free.

| pick_type | One-line definition | Formula (soft, weighted) | Tier |
|---|---|---|---|
| **group** *(reweight)* | Best group-aware print frame | area-weighted eyes + fraction expr − stragglers, sigmoid blur floor | **P0** — current signals |
| **everyone-eyes-open** | Max fraction of non-blinking faces | `frac_eyes` (area-weighted) + soft `no_blink` | P0 now / sharper with blink blendshape |
| **best-smile / joy** | Biggest genuine smile | `joy_max = max_i mouthSmile_i·(1+0.5·cheekSquint_i)` | small-extract (blendshape flag) |
| **best-moment / candid** *(refine)* | Decisive instant, no eyes gate | weighted joy + engagement + composition + soft-sharp + soft-eyes | P0 (proxy gaze) |
| **posed** *(new)* | Clean formal lineup | `mean(frontality)·(1−var)·arrangement_regularity` | small-extract |
| **sharpest** | Crispest technically | `squash(global_sharpness_raw)` | P0 now |
| **best-composed** | Strongest composition_score | thirds + headroom − crop − tilt + size/placement | P1 |
| **best-light** | Best-lit / dramatic | `face_exposure − clip + warmth + rim_rescue` | small-extract |
| **best-group-cohesion** | Most "everyone engaged" | `0.5·frac_engaged + 0.5·mean_engaged` | P0 now |
| **connection / couple-moment** | Two subjects engaged with each other | convergence(yaw+gaze), no frontality reward | new-extract (signed yaw) |
| **peak** | Burst apex | per-series argmax of `z(joy)+z(mouth_open)+z(disp)` | new-extract |
| **most-striking / wall-worthy** | Learned headline keeper | NIMA head + technical-quality + face/moment | new-model |
| **best of \<name\>** | Per-person best crop | existing `face_quality` per `person_id` — **already computed**, surface as a named pick | P0 now |

**P0 (ship from existing signals):** group reweight, everyone-eyes-open, best-moment, best-group-cohesion, sharpest, best-of-name.
**P1 (small extraction):** best-smile/joy, posed, best-composed, best-light, connection.
**Learned head:** most-striking/wall-worthy.

---

## 4. For everyone, not just pros

Most metrics above are pro-grain (bokeh, catchlight, rim light, Dutch angle). A small subset is what a **family/event host with 4,000 phone photos** actually cares about, and the UI should label these in plain words and surface them by default. All are P0/now from existing signals:

| Plain-language pick / stat | What it means | Backing metric | UI label |
|---|---|---|---|
| "Everyone's eyes are open" | No one caught mid-blink | area-weighted `frac_eyes` + per-face `no_blink` | **"Nobody blinked"** + live "8/8 eyes open" badge |
| "Everyone's smiling" | No straggler frowning | `frac_smile` | **"Everyone smiling"** / "7/8 smiling" |
| "Everyone's looking" | No one turned away | `frac_front` (head direction) | **"Everyone facing the camera"** |
| "The fun one" | The genuine laugh / candid moment | `joy_max` / `moment` pick | **"The fun moment"** |
| "Best of \<person\>" | Sharpest, best-lit frame of each person | per-person `face_quality` | **"Best photo of Mom"** |
| "Hide the duplicates" | One keeper per near-identical burst | DINOv2 cosine MMR | **"Hide near-duplicates"** toggle |

Design rule for this audience: show the **count** ("8/8 eyes open"), not the score. The soft model is what makes this honest — "the fun moment" can win *even with* "7/8 eyes open," exactly the product-owner ask. Never present a hard "rejected: blink" verdict; present "we picked the frame where the most people looked good."

---

## 5. Roadmap

### P0 — Reweight + soft gate + 2–3 new picks from current signals (no new extraction)

| Work | Signal needed | Effort |
|---|---|---|
| Rewrite `_eyes_aggregate`/`print_score`: area-weighted eyes + fraction expr + straggler penalty | stored `eye_open`/`smile`/`frontality`/`bbox` | ~½ day |
| Replace ×0.25 blur step with `sigmoid` floor in print/candid | stored `global_sharpness_raw` | ~1 hr |
| `best-group-cohesion`, `everyone-eyes-open`, `sharpest`, `best-of-name` picks | stored scalars | ~½ day each |
| `moment` pick via `soft_eyes_aggregate()` (gaze proxied by frontality+eye_open) | stored scalars + bbox | ~1 day |
| Crop-safety edge-touch soft gate; subject-size router | bbox + W,H | ~½ day |
| Wire `pick_feedback` export → warm-started linear reweighter | `pick_feedback` (v9, exists) | ~1–2 days |

### P1 — Small MediaPipe extractions (one-flag options + new columns + rescore pass)

| Work | Signal needed | Effort |
|---|---|---|
| `output_face_blendshapes=True` → genuine smile/joy, grimace, talking, blink | landmarks.py flag + score.py consumers + columns | ~1–1.5 days + rescore |
| `output_facial_transformation_matrixes=True` → head yaw/pitch/roll | one flag + Euler + 3 columns + migration | ~1 day + rescore |
| Gaze/eye-contact from iris (already in mesh, unread) | iris indices in score.py + 1 column | ~1 day + rescore |
| Skin-tone exposure (face L + skin mask) → `PRINT_W_FACE_EXPO` | face thumb + mask + columns | ~1.5 days + rescore |
| Highlight-clip / shadow-crush soft penalties | recompute clip fractions at index | ~1 day |
| Subject-vs-bg sharpness + focus-missed: store `bg_sharpness_raw` | index.py masked Laplacian + migration | ~1 day + reindex |
| Composition extracts: horizon-tilt, negative-space, headroom/thirds → `composition_score` + `best-composed` | `gray_small` + numpy helpers | ~2–3 days |
| `posed` pick + candid refine | stored scalars | ~1 day |

Signed-yaw picks (`connection`, lead-room) need persisting detector kps (discarded today) + reindex — schedule with the matrix-yaw work, which supplies a cleaner signed yaw anyway.

### P2 — Learned aesthetic/quality head trained on pick-feedback

| Work | Signal needed | Effort |
|---|---|---|
| NIMA-style head (384→1 or 384→10-bin EMD) on stored `global_embedding`, AVA cold start | stored embeddings | ~3–5 days incl. training harness |
| Pairwise RankNet from `pick_feedback` + buckets, conditioned on `pick_type` | feedback (exists), ≥~100 labels | ~1 week; write back to `_SCORE_COL` |
| `wall_worthy` / `most-striking` pick on the heads | learned heads + face/moment | ~2 days |
| Scene-diversity (HDBSCAN over embeddings) + cross-series MMR dedup | stored embeddings | ~2–3 days |

The P0/P1 columns are also the **features** for P2, and `pick_feedback` is already being collected — so every shipped pick improves the training set for the learned heads that eventually replace the hand-tuned weights. Nothing in P2 changes the read-time picker plumbing; it only changes the numbers in the existing `_SCORE_COL` columns.

---

**Key files:** scoring `atelier/quality.py`; weights `atelier/config.py` (`PICK_TYPES`, `PRINT_W_*`, `FACE_W_*`, `AESTHETIC_W_*`); picks/feedback `atelier/server.py` (`_SCORE_COL`, picks loop, feedback export); extraction `atelier/pipeline/index.py` + `atelier/pipeline/score.py`; landmarks `atelier/landmarks.py`.
