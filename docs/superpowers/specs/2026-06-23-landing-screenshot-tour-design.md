# Landing page — screenshot tour redesign

**Date:** 2026-06-23
**Target:** `website/public/` (the public marketing site, deployed to GitHub Pages)
**Status:** approved design, ready for implementation plan

## Goal

Turn the text-heavy marketing page into a visual **features demo**: real Atelier
screenshots (faces blurred) carry the page, prose is cut hard, and a single gold
**contour thread** threads every feature panel together. Decide and ship the
mobile treatment.

## Locked decisions

1. **Faces:** blur **everyone uniformly** — guests and the couple — via one CSS
   rule. No per-person targeting. Real personal **name labels** are also
   neutralized (PII). The site is public and search-indexable; this is the safe
   default.
2. **Live demo:** **removed.** The page becomes screenshots-only — each feature
   is a real screenshot + one short caption. The interactive cull widget and its
   `demo.js` are dropped from the page.
3. **Motif:** a continuous **contour thread** — one thin gold (`#cda35c`) SVG
   sine path running top→bottom; feature panels hang off it, alternating
   left/right on desktop.
4. **Mobile:** thread collapses to a **left-edge rail**; panels stack
   single-column; each wide desktop shot is shown as a **focal crop** with
   **tap → full-screen lightbox**.
5. **Tour length:** **5 panels** (strongest): review desk, people shelf, face
   detail, run console, print list / buckets.

## Source data

Screenshots come from the live app (`http://localhost:5050`) against the real
project `wedding-anjanan-bharath` (`~/.atelier/wedding-anjanan-bharath/db.sqlite`):
5,592 images, 12,626 faces, 234 named persons, 907 bursts with keepers, all
scored. Rich enough for every panel. Named persons include real guest names →
must be neutralized in any shot that shows labels.

## Page architecture (after)

```
nav            trim links: Why · Workflow · Features · Install · GitHub
hero           headline + 1 lede + 1 CTA; hero shot = real review desk (blurred)
marquee        keep (cheap, on-brand)
contour tour   the new body — 5 panels alternating off the gold thread
privacy        keep — short promise strip + honest MediaPipe fine-print
install        keep, trimmed — terminal block + platform grid
footer         update credit line (no longer Picsum/Pravatar)
```

### Contour tour — the 5 panels

Each panel: real screenshot (blurred) + kicker + one-line caption (≤12 words).
Panels alternate sides of the thread; a small bead node sits where each panel
meets the thread.

| # | Screenshot (app view) | Kicker | Caption |
|---|---|---|---|
| 1 | Review desk — stage + inspector + filmstrip | Burst-aware picks | Every burst, one keeper — scored per intent. |
| 2 | People tab — face grid sidebar | Faces, sorted | Thousands of faces → people. Merge, split, rename. |
| 3 | Face-detail modal — crop + quality bars | Reads the frame | Eyes, gaze, smile, sharpness — read per face. |
| 4 | Run console — phases + live face grid | Resumable runs | Index 20k off a drive, walk away. It resumes. |
| 5 | Print list / buckets — keepers grid | Your cut | Star the keeper. Buckets are yours. Originals never move. |

## Contour thread — implementation

- **Desktop:** a vertical SVG (or per-panel SVG segments) drawing a sine path in
  `#cda35c` at low opacity (~0.35), centered. Panels are a two-column grid; odd
  panels sit left of the thread, even panels right, each connected by a short
  horizontal stub + a gold bead (`●` / `★`) on the thread.
- **Reveal:** the thread draws in on scroll (`stroke-dasharray` /
  `stroke-dashoffset` animated as the section enters), panels fade/slide in
  (reuse existing `.reveal` IntersectionObserver in `site.js`).
- **Mobile (≤720px):** thread becomes a fixed-position left **rail** (x ≈ 20px);
  panels become a single column to its right; beads sit on the rail. The
  alternating layout collapses to one column.

## Screenshots — capture & blur procedure

Capture with the chrome-devtools MCP against the running app, 2× device pixel
ratio for crisp UI chrome.

For each view:
1. Navigate to the view in the wedding project; wait for thumbnails/faces to load.
2. **Inject a blur/neutralize stylesheet** before capture:
   - Apply `filter: blur(7px)` to every face-crop / photo image element in the
     rendered DOM (people-grid face crops, filmstrip frames, the review stage
     image, face-detail crop, live-face-grid crops, print-list thumbnails).
   - **Neutralize name labels:** replace or hide any element rendering a
     person's `display_name` (swap text → "Guest", or hide the label). Confirm
     the exact selectors against the live DOM at capture time (the app's
     `web/*.js` render these; enumerate them, don't guess).
   - Blur strength is tuned so the photographic content is unidentifiable but the
     UI chrome (bars, tags, pills, layout) stays crisp.
3. Screenshot the framed view (full view or a tight region per panel).
4. Save PNG → convert to WebP → `website/public/assets/shots/<panel>.webp`.
   Record intrinsic `width`/`height`; add `loading="lazy"` + `decoding="async"`
   in markup. Keep a 2× asset where it helps retina sharpness.

**Verification:** before commit, open each saved shot and confirm **no
identifiable face and no real personal name** is legible. This is a hard gate —
the page is public.

## Mobile spec (locked)

- Thread → left rail; panels single-column.
- Each wide shot rendered as a **focal crop** (CSS `object-fit: cover` +
  `object-position` on the meaningful region) at a phone-friendly aspect.
- **Tap → full lightbox:** a lightweight lightbox (added to `site.js`) shows the
  full uncropped (still blurred) shot; backdrop + close on tap/Esc.

## Code deltas

- **`index.html`:** remove the entire `#demo` interactive section markup; remove
  the `<script src="js/demo.js">`; replace `why` / `features` / `people` /
  `how` text blocks with the contour-tour markup; trim hero copy; update footer
  credit line.
- **`demo.js`:** no longer referenced by the page. Delete the file (it only
  powered the dropped widget + synthetic generators: peopleShelf, sheet-frames,
  printlist).
- **`site.js`:** keep reveal-on-scroll; **add** the lightbox + the contour-thread
  draw-on-scroll trigger.
- **`style.css`:** add contour-thread + panel + lightbox styles; remove
  now-dead demo/widget/synthetic styles.
- **`assets/shots/`:** new — the 5 (+hero) captured WebP screenshots.

## Non-goals / out of scope

- No change to the app itself (`atelier/web/*`) — capture only.
- No per-person un-blur, no couple exception (explicitly rejected).
- No new fonts/brand colors — reuse Fraunces / Hanken Grotesk / JetBrains Mono
  and the existing warm-dark + gold palette.
- The `how` 4-step pipeline and the 8-card feature grid are replaced by the
  5-panel tour; their essential content folds into captions. Not a separate
  rebuild.

## Acceptance criteria

- Page renders 5 screenshot panels woven on a single gold contour thread;
  desktop alternates sides, mobile is a left-rail single column.
- No interactive demo, no `demo.js` reference; page weight drops.
- Every published screenshot: faces blurred, no legible real name. Verified by
  eye before commit.
- Mobile: focal crops legible; tap opens a full lightbox; thread visible as a
  left rail.
- `eslint` clean on `site.js`; HTML validates; deploys via the existing
  `pages.yml` workflow on push to `main`.
