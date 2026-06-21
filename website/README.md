# Atelier — marketing / demo site

A static, single-page site that explains what Atelier is and lets visitors **try the Review / cull view live** in the browser (on synthetic bursts — no install, no backend). Hosted on **Firebase Hosting**.

```
website/
  firebase.json        # Firebase Hosting config (public/ is the web root)
  .firebaserc          # ← set your Firebase project id here
  public/
    index.html         # the page
    css/style.css       # "darkroom atelier" design system
    js/demo.js          # the interactive cull widget (mirrors atelier/web/cull.js)
    js/site.js          # nav, scroll reveals, copy button, decorative imagery
```

It is pure HTML/CSS/JS — no build step, no framework, no server. The interactive demo is entirely client-side. Stock demo imagery is pulled from Lorem Picsum and Pravatar at view time (each `<img>` falls back to a warm gradient if a request fails), so the only thing the site needs at runtime is the visitor's browser.

## Preview locally

```bash
cd website/public
python3 -m http.server 5055      # → http://localhost:5055
# or, with the Firebase CLI:
cd website && firebase emulators:start --only hosting
```

## Deploy

```bash
npm install -g firebase-tools          # once
firebase login                         # once

cd website
# point it at your project (creates/updates .firebaserc):
firebase use --add                     # pick or create the Firebase project
firebase deploy --only hosting
```

`firebase use --add` writes the chosen project id into `.firebaserc` (replacing the
`REPLACE_WITH_YOUR_FIREBASE_PROJECT_ID` placeholder). After the first deploy the
site is live at `https://<project-id>.web.app`.

## Notes

- **Keep it in sync with the app.** Copy, keyboard shortcuts, and the demo's
  pick/star/bucket behaviour mirror `atelier/web/cull.js`. If the real Review view
  changes, update `public/js/demo.js` to match.
- **No real photos are committed.** The demo fakes burst variation with CSS
  filters over one base image per burst plus synthetic per-frame scores — enough
  to teach the concept without shipping or uploading anyone's shoot.
