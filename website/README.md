# Atelier — marketing site

A static, single-page site that shows what Atelier is through **real screenshots of
the app** — a guided tour woven on a gold "contour thread". No build step, no
framework, no backend.

```
website/
  firebase.json        # legacy Firebase Hosting config (deploy is GitHub Pages)
  public/
    index.html         # the page (hero + 5-panel screenshot tour + privacy + install)
    css/style.css      # "darkroom atelier" design system
    js/site.js         # nav, scroll reveals, screenshot lightbox, copy button
    assets/shots/      # the tour screenshots (WebP) — see "Screenshots" below
```

It is pure HTML/CSS/JS — the only runtime dependency is the visitor's browser and
Google Fonts. The page is deployed to **GitHub Pages** by
`.github/workflows/pages.yml` on every push to `main` that touches
`website/public/**`; it serves at `https://bharathksunil.github.io/atelier/`.

## Screenshots

The tour uses **real captures of the running app** against a live wedding project,
not mockups. Every face is **blurred** and every personal name is **neutralized**
before capture — the site is public and search-indexable, so no guest is
identifiable and no real name is legible. Captures live in `public/assets/shots/`:

```
hero-review.webp   review desk — keeper of a burst (hero)
review-desk.webp   review desk — burst-aware picks + frame-quality bars
people-shelf.webp  faces grouped into named people (labels → "Guest N")
face-detail.webp   one face + plain-language quality bars
run-console.webp   pipeline phases + live grid of faces found
buckets.webp       named collections over a grid of keepers
```

To re-capture: open the app, blur all photo images
(`img[src*="/api/p/"] { filter: blur(16px) }`), replace any person name labels
with generic text, then screenshot each view. **Verify by eye that no face or real
name is legible before committing** — this is a hard requirement.

## Preview locally

```bash
cd website/public
python3 -m http.server 5055      # → http://localhost:5055
```

## Notes

- **No identifiable people are committed.** Faces are blurred and names neutralized
  in every shot.
- The interactive in-browser demo was removed in favour of the screenshot tour;
  there is no longer a `demo.js`.
