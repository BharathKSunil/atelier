/* ============================================================
   Atelier demo — an in-browser slice of the Review / cull view.
   Mirrors atelier/web/cull.js behaviour on synthetic bursts:
   frozen filmstrip order, auto vs manual picks, star→print list,
   range-star, buckets, and the full keyboard flow.
   ============================================================ */
(() => {
  "use strict";

  // ── synthetic project ────────────────────────────────────
  const BUCKETS = [
    { id: 1, name: "Socials", color: "#cda35c" },
    { id: 2, name: "Candids", color: "#82b39f" },
    { id: 3, name: "Album", color: "#7d9fc9" },
    { id: 4, name: "Private", color: "#cf8f76" },
  ];

  const META = {
    group: { label: "Everyone", desc: "Everyone looking good — eyes open, sharp." },
    candid: { label: "Candid", desc: "Natural, un-posed — a real moment." },
    aesthetic: { label: "Striking", desc: "Most visually striking frame." },
  };
  const ORDER = ["group", "candid", "aesthetic"];

  // tone = a CSS filter so near-identical burst frames read as distinct takes
  const f = (sharp, eyes, smile, front, print, candid, aes, tone, blink) => ({
    sharp, eyes, smile, front, print, candid, aes, tone: tone || "", blink: !!blink,
  });

  const BURSTS = [
    {
      seed: "atelier-vows",
      caption: "The vows · 6 frames",
      frames: [
        f(0.71, 0.93, 0.55, 0.9, 0.74, 0.62, 0.68, "brightness(.96)"),
        f(0.88, 0.95, 0.78, 0.95, 0.93, 0.7, 0.86, ""), // group keeper
        f(0.84, 0.12, 0.7, 0.92, 0.41, 0.66, 0.8, "brightness(.9) saturate(.85)", true), // blink
        f(0.79, 0.9, 0.94, 0.88, 0.86, 0.95, 0.82, "contrast(1.05)"), // candid
        f(0.64, 0.88, 0.6, 0.7, 0.66, 0.58, 0.71, "blur(.5px) brightness(.92)"), // soft
        f(0.82, 0.91, 0.66, 0.83, 0.88, 0.64, 0.96, "saturate(1.12) contrast(1.04)"), // striking
      ],
    },
    {
      seed: "atelier-confetti",
      caption: "Confetti exit · 5 frames",
      frames: [
        f(0.6, 0.86, 0.8, 0.74, 0.69, 0.9, 0.78, "brightness(.94)"),
        f(0.83, 0.92, 0.88, 0.86, 0.9, 0.82, 0.91, ""), // group
        f(0.55, 0.84, 0.95, 0.7, 0.72, 0.97, 0.85, "contrast(1.06) saturate(1.1)"), // candid
        f(0.7, 0.3, 0.6, 0.8, 0.5, 0.55, 0.7, "brightness(.88)", true), // blink
        f(0.8, 0.9, 0.72, 0.82, 0.86, 0.7, 0.95, "saturate(1.15)"), // striking
      ],
    },
    {
      seed: "atelier-family",
      caption: "Family portrait · 7 frames",
      frames: [
        f(0.74, 0.6, 0.62, 0.92, 0.7, 0.5, 0.66, "brightness(.95)"),
        f(0.9, 0.96, 0.8, 0.97, 0.95, 0.64, 0.84, ""), // group keeper
        f(0.86, 0.55, 0.7, 0.95, 0.62, 0.6, 0.8, "contrast(1.03)"), // one looking away
        f(0.7, 0.2, 0.75, 0.9, 0.44, 0.58, 0.74, "brightness(.9)", true), // blink
        f(0.82, 0.9, 0.9, 0.84, 0.84, 0.93, 0.81, "saturate(1.08)"), // candid
        f(0.78, 0.88, 0.64, 0.8, 0.8, 0.6, 0.94, "saturate(1.16) contrast(1.05)"), // striking
        f(0.66, 0.85, 0.58, 0.72, 0.68, 0.55, 0.7, "blur(.4px)"), // soft
      ],
    },
    {
      seed: "atelier-firstdance",
      caption: "First dance · 5 frames",
      frames: [
        f(0.62, 0.88, 0.7, 0.7, 0.7, 0.84, 0.86, "brightness(.9)"),
        f(0.8, 0.93, 0.82, 0.84, 0.89, 0.78, 0.9, ""), // group
        f(0.58, 0.9, 0.96, 0.66, 0.74, 0.98, 0.88, "contrast(1.05)"), // candid
        f(0.76, 0.91, 0.7, 0.8, 0.85, 0.7, 0.97, "saturate(1.2) contrast(1.06)"), // striking
        f(0.68, 0.4, 0.6, 0.78, 0.52, 0.6, 0.72, "brightness(.86)", true), // blink
      ],
    },
  ];

  // assign stable global ids + derive auto picks per burst
  BURSTS.forEach((b, bi) => {
    b.id = bi;
    b.frames.forEach((fr, i) => {
      fr.id = `${bi}-${i}`;
      fr.idx = i;
    });
    const top = (key) => b.frames.reduce((a, c) => (c[key] > a[key] ? c : a)).id;
    b.autoPicks = { group: top("print"), candid: top("candid"), aesthetic: top("aes") };
  });

  const PCT = (x) => `${Math.round(x * 100)}`;

  // ── state ────────────────────────────────────────────────
  let pos = 0;
  let heroId = null;
  let displayFrames = [];
  const printSet = new Set(); // starred frame ids → "print list"
  const manual = {}; // `${burstId}` -> {group,candid,aesthetic} (image id)
  const bucketMem = new Map(); // frameId -> Set(bucketId)
  let focused = false;

  const el = (id) => document.getElementById(id);
  const burst = () => BURSTS[pos];
  const frames = () => burst().frames;
  const picks = () => {
    const m = manual[pos] || {};
    const ap = burst().autoPicks;
    const out = {};
    ORDER.forEach((t) => {
      if (m[t]) out[t] = { image_id: m[t], source: "manual" };
      else out[t] = { image_id: ap[t], source: "auto" };
    });
    return out;
  };
  const hero = () => frames().find((x) => x.id === heroId) || frames()[0];
  const memOf = (id) => bucketMem.get(id) || new Set();

  // ── toast (shared) ───────────────────────────────────────
  let toastT = null;
  function toast(msg, err) {
    const t = el("toast");
    if (!t) return;
    t.textContent = msg;
    t.classList.toggle("err", !!err);
    t.classList.add("show");
    clearTimeout(toastT);
    toastT = setTimeout(() => t.classList.remove("show"), 1900);
  }
  window.__atelierToast = toast;

  const seedUrl = (seed, w, h) => `https://picsum.photos/seed/${seed}/${w}/${h}`;

  // ── load a burst: freeze filmstrip order ONCE ────────────
  function load() {
    const b = burst();
    const pk = picks();
    heroId = pk.group.image_id || frames()[0].id;
    const byImg = byImgMap();
    const featured = (fr) => byImg[fr.id] || printSet.has(fr.id);
    displayFrames = [...frames().filter(featured), ...frames().filter((fr) => !featured(fr))];
    render();
  }

  function byImgMap() {
    const pk = picks();
    const byImg = {};
    ORDER.forEach((t) => {
      const p = pk[t];
      if (p && p.image_id) (byImg[p.image_id] = byImg[p.image_id] || []).push({ t, source: p.source });
    });
    return byImg;
  }

  // ── render everything ────────────────────────────────────
  function render() {
    const b = burst();
    const h = hero();
    const byImg = byImgMap();

    el("rvCount").textContent = `Burst ${pos + 1} of ${BURSTS.length} · ${frames().length} frames · ${b.caption.split("·")[0].trim()}`;
    el("rvProgress").style.width = `${((pos + 1) / BURSTS.length) * 100}%`;

    // stage
    const inPrint = printSet.has(h.id);
    const recId = b.autoPicks.group;
    el("rvStage").innerHTML =
      `${inPrint ? '<span class="stage-badge">★ In print list</span>' : ""}` +
      `${h.id === recId ? '<span class="stage-rec">recommended</span>' : ""}` +
      `<img src="${seedUrl(b.seed, 900, 600)}" alt="${b.caption}" style="filter:${h.tone || "none"}">` +
      `<span class="stage-zoom">click to zoom · ↵</span>`;

    // star button
    const sb = el("rvStar");
    sb.textContent = inPrint ? "★ In print list" : "☆ Add to print list";
    sb.classList.toggle("accent", inPrint);

    // inspector
    renderInspector(h, byImg);

    // filmstrip (frozen order; refresh tags/highlight in place)
    el("rvStrip").innerHTML = displayFrames
      .map((fr) => {
        const chips = (byImg[fr.id] || [])
          .map((p) => `<span class="ftag ${p.t} ${p.source}">${META[p.t].label}</span>`)
          .join("");
        const dots = [...memOf(fr.id)]
          .map((bid) => {
            const bk = BUCKETS.find((x) => x.id === bid);
            return bk ? `<span class="bk-dot" style="background:${bk.color}"></span>` : "";
          })
          .join("");
        return `<div class="frame-thumb ${fr.id === heroId ? "cur" : ""} ${printSet.has(fr.id) ? "star" : ""}"
          data-id="${fr.id}" role="option" tabindex="0" aria-selected="${fr.id === heroId}"
          aria-label="Frame, print ${PCT(fr.print)}%${printSet.has(fr.id) ? ", in print list" : ""}">
          <img loading="lazy" src="${seedUrl(b.seed, 240, 160)}" alt="" style="filter:${fr.tone || "none"}">
          ${dots ? `<div class="bk-dots">${dots}</div>` : ""}
          <div class="tags">${chips}</div></div>`;
      })
      .join("");
    el("rvStrip")
      .querySelectorAll(".frame-thumb")
      .forEach((node) => {
        const act = (e) => {
          const id = node.dataset.id;
          if (e && e.shiftKey) return rangeStar(id);
          heroId = id;
          render();
          node.scrollIntoView({ block: "nearest", inline: "center" });
        };
        node.onclick = act;
        node.onkeydown = (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            act(e);
          }
        };
      });

    renderBuckets();
    renderPrintList();
  }

  function renderInspector(h, byImg) {
    const tags = (byImg[h.id] || []).map((p) => META[p.t].label);
    let why;
    if (h.blink) why = `<b>One subject blinked</b> — eyes ${PCT(h.eyes)}%. Auto-disqualified as the group keeper.`;
    else if (h.id === burst().autoPicks.group) why = `<b>The keeper.</b> Everyone sharp, eyes open — the safe group pick.`;
    else if (h.id === burst().autoPicks.candid) why = `<b>Most candid.</b> Natural expression, unposed — smile ${PCT(h.smile)}%.`;
    else if (h.id === burst().autoPicks.aesthetic) why = `<b>Most striking.</b> Strongest overall composition of the burst.`;
    else why = `A solid frame, just edged out on print score by the keeper.`;

    el("rvInspector").innerHTML = `
      <div class="insp-head">Frame ${h.idx + 1} · scores</div>
      <div class="insp-score">${PCT(h.print)}<small>print score</small></div>
      <div class="insp-bars">
        ${bar("Sharpness", h.sharp)}
        ${bar("Eyes open", h.eyes, h.eyes < 0.5)}
        ${bar("Smile", h.smile)}
        ${bar("Frontality", h.front)}
      </div>
      <div class="insp-why">${why}${tags.length ? `<br><br>Tagged: ${tags.join(", ")}` : ""}</div>`;
  }
  const bar = (label, v, low) =>
    `<div class="bar-row"><span>${label}</span><div class="bar ${low ? "low" : ""}"><i style="width:${PCT(v)}%"></i></div></div>`;

  function renderBuckets() {
    const h = hero();
    const inSet = memOf(h.id);
    el("rvBuckets").innerHTML = BUCKETS.map(
      (b, i) =>
        `<button class="bk-chip ${inSet.has(b.id) ? "on" : ""}" data-id="${b.id}" style="--bc:${b.color}">
          <span class="k">${i + 1}</span>${b.name}</button>`,
    ).join("");
    el("rvBuckets")
      .querySelectorAll(".bk-chip")
      .forEach((c) => {
        c.onclick = () => toggleBucket(BUCKETS.find((x) => x.id === +c.dataset.id), hero().id);
      });
  }

  function renderPrintList() {
    el("plCount").textContent = printSet.size;
    const grid = el("plGrid");
    if (!printSet.size) {
      grid.innerHTML = `<p class="printlist-empty">Star frames in the desk above — your keepers collect here.</p>`;
      return;
    }
    // map each starred id back to its burst seed for a thumbnail
    const items = [];
    BURSTS.forEach((b) => b.frames.forEach((fr) => printSet.has(fr.id) && items.push({ b, fr })));
    grid.innerHTML = items
      .map(({ b, fr }) => `<img src="${seedUrl(b.seed, 120, 80)}" alt="keeper" style="filter:${fr.tone || "none"}">`)
      .join("");
  }

  // ── actions ──────────────────────────────────────────────
  function star() {
    const h = hero();
    if (printSet.has(h.id)) {
      printSet.delete(h.id);
      toast("Removed from print list");
    } else {
      printSet.add(h.id);
      toast("Added to print list");
    }
    render();
  }

  function rangeStar(targetId) {
    const a = displayFrames.findIndex((fr) => fr.id === heroId);
    const b = displayFrames.findIndex((fr) => fr.id === targetId);
    if (a < 0 || b < 0) return;
    const [lo, hi] = a < b ? [a, b] : [b, a];
    const slice = displayFrames.slice(lo, hi + 1).filter((fr) => !printSet.has(fr.id));
    if (!slice.length) return toast("Already in print list");
    slice.forEach((fr) => printSet.add(fr.id));
    toast(`Starred ${slice.length} frame${slice.length > 1 ? "s" : ""}`);
    render();
  }

  function setCriterion(t) {
    const h = hero();
    const m = (manual[pos] = manual[pos] || {});
    if (m[t] === h.id) {
      delete m[t]; // toggle off → revert to auto
      toast(`${META[t].label} → auto`);
    } else {
      m[t] = h.id;
      toast(`${META[t].label} → this frame`);
    }
    // featured set may change, but per cull.js the strip order stays frozen for the burst
    render();
  }

  function toggleBucket(b, id) {
    if (!b) return;
    const set = bucketMem.get(id) || bucketMem.set(id, new Set()).get(id);
    if (set.has(b.id)) {
      set.delete(b.id);
      toast(`Removed from ${b.name}`);
    } else {
      set.add(b.id);
      toast(`Added to ${b.name}`);
    }
    render();
  }
  function toggleBucketIdx(i) {
    const b = BUCKETS[i];
    if (b) toggleBucket(b, hero().id);
  }

  function step(d) {
    pos = (pos + d + BURSTS.length) % BURSTS.length;
    load();
  }
  function moveHero(d) {
    if (!displayFrames.length) return;
    let i = displayFrames.findIndex((fr) => fr.id === heroId);
    i = (i + d + displayFrames.length) % displayFrames.length;
    heroId = displayFrames[i].id;
    render();
    const node = el("rvStrip").querySelector(`.frame-thumb[data-id="${heroId}"]`);
    if (node) node.scrollIntoView({ block: "nearest", inline: "center" });
  }

  function starRecommended() {
    star(); // in the demo the recommended frame loads as hero; Star toggles it
  }

  // ── lightbox ─────────────────────────────────────────────
  function openLightbox() {
    const h = hero();
    const b = burst();
    let lb = el("demoLightbox");
    if (!lb) {
      lb = document.createElement("div");
      lb.id = "demoLightbox";
      lb.style.cssText =
        "position:fixed;inset:0;z-index:9600;background:rgba(8,6,4,.94);display:flex;align-items:center;justify-content:center;padding:5vh;cursor:zoom-out;opacity:0;transition:opacity .3s";
      lb.innerHTML = `<img style="max-width:100%;max-height:100%;border-radius:10px;box-shadow:0 40px 100px -30px #000">`;
      lb.onclick = () => {
        lb.style.opacity = "0";
        setTimeout(() => lb.remove(), 300);
      };
      document.body.appendChild(lb);
      requestAnimationFrame(() => (lb.style.opacity = "1"));
    }
    const img = lb.querySelector("img");
    img.src = seedUrl(b.seed, 1400, 933);
    img.style.filter = h.tone || "none";
  }

  // ── keyboard (scoped to the focused desk) ────────────────
  function onKey(e) {
    if (!focused) return;
    if (el("demoLightbox")) {
      if (e.key === "Escape") el("demoLightbox").click();
      return;
    }
    const k = e.key;
    const used = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " ", "Enter"];
    if (used.includes(k) || /^[1-9xXgGcCaAfF]$/.test(k)) e.preventDefault();

    if (k === "ArrowLeft") step(-1);
    else if (k === "ArrowRight" || k === "x" || k === "X") step(1);
    else if (k === "ArrowUp") moveHero(-1);
    else if (k === "ArrowDown") moveHero(1);
    else if (k === " ") star();
    else if (k >= "1" && k <= "9") toggleBucketIdx(+k - 1);
    else if (k === "g" || k === "G") setCriterion("group");
    else if (k === "c" || k === "C") setCriterion("candid");
    else if (k === "a" || k === "A") setCriterion("aesthetic");
    else if (k === "Enter") openLightbox();
  }

  // ── wire up ──────────────────────────────────────────────
  function setFocus(on) {
    focused = on;
    const shell = el("cull");
    shell.classList.toggle("focused", on);
    el("kbdLabel").textContent = on ? "keyboard live" : "click to focus";
  }

  function init() {
    const shell = el("cull");
    if (!shell) return;
    shell.addEventListener("focusin", () => setFocus(true));
    shell.addEventListener("focusout", (e) => {
      if (!shell.contains(e.relatedTarget)) setFocus(false);
    });
    shell.addEventListener("mouseenter", () => setFocus(true));
    shell.addEventListener("mouseleave", () => {
      if (!shell.contains(document.activeElement)) setFocus(false);
    });
    shell.addEventListener("click", () => shell.focus({ preventScroll: true }));
    window.addEventListener("keydown", onKey);

    el("rvPrev").onclick = () => step(-1);
    el("rvNext").onclick = () => step(1);
    el("rvStar").onclick = star;
    el("rvStage").onclick = openLightbox;

    load();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
