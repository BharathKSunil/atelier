// Review / cull: step through bursts in capture sequence, inspect per-person stats,
// zoom in place (works in fullscreen), star keepers, bucket frames, and rate the
// auto picks for retraining. Burst position + reviewed-state survive a reload.
import { api, post, pct, escapeHtml, toast } from "./api.js";
import { openFaceModal } from "./faces.js";

const META = {
  group: { label: "Group", desc: "Best group frame — eyes open, sharp (eyes strict)." },
  everyone: { label: "All eyes", desc: "Most people eyes-open, smiling, facing." },
  smile: { label: "Smile", desc: "Biggest smile in the frame." },
  candid: { label: "Candid", desc: "Natural, un-posed — soft on eyes." },
  moment: { label: "Moment", desc: "The decisive frame — a great shot can beat a blink." },
  aesthetic: { label: "Striking", desc: "Most visually striking frame." },
};
const ORDER = ["group", "everyone", "smile", "candid", "moment", "aesthetic"];
const FILTER_MODE_LABEL = { solo: "solo", group: "with others", together: "together", only: "only these" };
const LAYOUT_KEY = "atelier:rv-layout3"; // bumped: faces now float over the photo; panel = quality+feedback
const DEFAULT_LAYOUT = { inspW: 320, stripH: 142, inspOpen: true, inspSide: "right" };

let slug = null;
let series = []; // [{id, frame_count, time_start, reviewed_at}]
let total = 0; // server-side total (denominator), independent of how many pages loaded
let pos = 0;
let frames = []; // current burst frames in CAPTURE SEQUENCE (server order) — never reordered
let picks = {}; // pick_type -> {image_id, source}
let byImg = {}; // image_id -> [{t, source}] for tag chips
let heroId = null;
let buckets = [];
let imgBuckets = {}; // image_id -> Set(bucket_id)
let faces = []; // detected faces for the current hero (floating chips)
let activeFace = null; // {f, chip} currently hovered/selected face overlay
let faceIdx = -1; // keyboard cursor into faces[] for Tab cycling
let fbOpen = false; // feedback accordion expanded? (collapsed by default)
let feedback = {}; // pick_type -> {verdict, better_image_id, note} for the current burst
let sortMode = "time";
let layout = { ...DEFAULT_LAYOUT };
let keyHandler = null;
let reviewed = new Set(); // series ids marked reviewed (server-backed)

// Filter mode: People → "Review solo / with others" opens the SAME cull desk scoped to
// a flat set of a person's photos (no series/picks). reviewFilter is a one-shot set by
// people.js right before navigating; mountReview consumes it into activeFilter.
let reviewFilter = null;
let activeFilter = null;
export function setReviewFilter(f) {
  reviewFilter = f;
}

// zoom/pan state for the stage hero
const zoom = { scale: 1, tx: 0, ty: 0, panning: false, sx: 0, sy: 0 };

// ---- small localStorage helpers (best-effort) ----
function lsGet(key, fallback) {
  try {
    const v = JSON.parse(localStorage.getItem(key));
    return v == null ? fallback : v;
  } catch {
    return fallback;
  }
}
function lsSet(key, val) {
  try {
    localStorage.setItem(key, JSON.stringify(val));
  } catch {}
}
const posKey = () => `atelier:rv-pos:${slug}`;

export async function mountReview(s) {
  slug = s;
  series = [];
  total = 0;
  reviewed = new Set();
  activeFilter = reviewFilter; // one-shot drill-down from People; cleared so the tab is normal next time
  reviewFilter = null;
  layout = { ...DEFAULT_LAYOUT, ...lsGet(LAYOUT_KEY, {}) };
  applyLayout();

  if (!keyHandler) {
    keyHandler = onKey;
    window.addEventListener("keydown", keyHandler);
  }
  wireChrome();

  const sortLbl = document.querySelector(".rv-sort");
  if (sortLbl) sortLbl.classList.toggle("hidden", !!activeFilter); // sort is series-only
  const sortSel = document.getElementById("rv-sort");
  if (sortSel) {
    sortSel.value = sortMode;
    sortSel.onchange = async () => {
      sortMode = sortSel.value;
      pos = 0;
      await loadSeries();
    };
  }

  if (activeFilter) await loadFilterSet();
  else await loadSeries();
}

// ---- filter mode: a person's photos as one flat stepping set (no series/picks) ----
async function loadFilterSet() {
  const mySlug = slug;
  buckets = await api(`/api/p/${slug}/buckets`).catch(() => []);
  const who = activeFilter.persons ? `persons=${activeFilter.persons.join(",")}` : `person=${activeFilter.person}`;
  const imgs = await api(`/api/p/${slug}/review-set?${who}&mode=${encodeURIComponent(activeFilter.mode)}`).catch(
    () => [],
  );
  if (slug !== mySlug) return;
  series = imgs.length ? [{ id: "filter", frame_count: imgs.length }] : [];
  total = series.length;
  if (!imgs.length) {
    emptyState(`No ${FILTER_MODE_LABEL[activeFilter.mode] || activeFilter.mode} photos for ${activeFilter.label}.`);
    return;
  }
  pos = 0;
  frames = imgs;
  picks = {};
  feedback = {};
  byImg = {};
  imgBuckets = {};
  heroId = frames[0].id;
  seedDefaultMembership();
  faces = [];
  resetZoom();
  render();
  scrollHeroIntoView();
  const ids = frames.map((f) => f.id).join(",");
  if (ids && buckets.length) {
    api(`/api/p/${slug}/buckets/for-images?ids=${ids}`)
      .then((mem) => {
        if (slug !== mySlug) return;
        Object.entries(mem).forEach(([iid, arr]) => (imgBuckets[+iid] = new Set(arr)));
        render();
      })
      .catch(() => {});
  }
  loadFaces(mySlug, pos);
}

export function unmountReview() {
  if (keyHandler) {
    window.removeEventListener("keydown", keyHandler);
    keyHandler = null;
  }
}

// ---- series list: render after page 1, keep paging in the background ----
async function loadSeries() {
  const mySlug = slug;
  series = [];
  let off = 0;
  let first = true;
  while (true) {
    const r = await api(`/api/p/${slug}/series?sort=${sortMode}&offset=${off}&limit=200`).catch(() => null);
    if (slug !== mySlug) return; // navigated away mid-fetch
    if (!r) break;
    total = r.total ?? series.length + (r.items || []).length;
    series.push(...(r.items || []));
    (r.items || []).forEach((s) => s.reviewed_at != null && reviewed.add(s.id));
    if (first) {
      first = false;
      buckets = await api(`/api/p/${slug}/buckets`).catch(() => []);
      if (slug !== mySlug) return;
      if (!series.length) {
        emptyState();
        // keep paging only if total says there should be more (there won't be)
      } else {
        pos = Math.min(Math.max(0, lsGet(posKey(), 0)), series.length - 1);
        await load();
      }
    }
    if (r.next_offset == null) break;
    off = r.next_offset;
  }
  updateProgress();
}

function emptyState(msg) {
  document.getElementById("rv-stage").innerHTML =
    `<div class="empty-stage">${escapeHtml(msg || "No multi-frame bursts to review.")}</div>`;
  document.getElementById("rv-strip").innerHTML = "";
  document.getElementById("rv-inspector").innerHTML = "";
  document.getElementById("rv-count").textContent = "—";
}

async function load() {
  if (!series.length) return;
  const sid = series[pos].id;
  const mySlug = slug,
    myPos = pos;
  resetZoom();
  const [fr, pk, fb] = await Promise.all([
    api(`/api/p/${slug}/series/${sid}/images`),
    api(`/api/p/${slug}/series/${sid}/picks`).then((d) => {
      const m = {};
      (d.picks || []).forEach((p) => {
        m[p.pick_type] = { image_id: p.image_id, source: p.source };
      });
      return m;
    }),
    api(`/api/p/${slug}/series/${sid}/feedback`).catch(() => ({})),
  ]);
  if (slug !== mySlug || pos !== myPos) return; // navigated away — drop stale data
  frames = fr; // capture sequence; DO NOT reorder
  picks = pk;
  feedback = fb || {};
  heroId = (picks.group && picks.group.image_id) || (frames[0] && frames[0].id);
  byImg = {};
  ORDER.forEach((t) => {
    const p = picks[t];
    if (p) (byImg[p.image_id] = byImg[p.image_id] || []).push({ t, source: p.source });
  });
  imgBuckets = {};
  seedDefaultMembership();
  faces = [];
  render();
  scrollHeroIntoView();

  // secondary fetches — paint first, enrich after
  const ids = frames.map((f) => f.id).join(",");
  if (ids && buckets.length) {
    api(`/api/p/${slug}/buckets/for-images?ids=${ids}`)
      .then((mem) => {
        if (slug !== mySlug || pos !== myPos) return;
        Object.entries(mem).forEach(([iid, arr]) => (imgBuckets[+iid] = new Set(arr)));
        render();
      })
      .catch(() => {});
  }
  loadFaces(mySlug, myPos);
}

async function loadFaces(mySlug, myPos) {
  const h = hero();
  if (!h) return;
  const fc = await api(`/api/p/${slug}/image/${h.id}/faces`).catch(() => []);
  if (slug !== mySlug || pos !== myPos || hero().id !== h.id) return;
  faces = fc || [];
  renderFaceChips();
  renderInspector();
}

function hero() {
  return frames.find((f) => f.id === heroId) || frames[0];
}

// ===================== render =====================
function render() {
  const h = hero();
  if (activeFilter) {
    const i = frames.findIndex((f) => f.id === heroId);
    const cnt = document.getElementById("rv-count");
    cnt.innerHTML = `<span class="rv-exit" id="rv-exit" role="button" tabindex="0" title="Back to all bursts">‹ exit</span> ${escapeHtml(activeFilter.label)} · ${FILTER_MODE_LABEL[activeFilter.mode] || activeFilter.mode} · ${i + 1} of ${frames.length}`;
    const ex = document.getElementById("rv-exit");
    ex.onclick = exitFilter;
    ex.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        exitFilter();
      }
    };
  } else {
    document.getElementById("rv-count").textContent = series.length
      ? `Burst ${pos + 1} of ${total || series.length} · ${frames.length} frames${reviewed.has(series[pos].id) ? " · reviewed ✓" : ""}`
      : "—";
  }
  // hide series-only chrome in filter mode (sort, star-recommended)
  const rec = document.getElementById("rv-star-rec");
  if (rec) rec.classList.toggle("hidden", !!activeFilter);
  updateProgress();

  const dbName = (defaultBucket() || {}).name || "print list";

  // stage with in-place zoom + a floating face overlay (chips + leader line)
  const stage = document.getElementById("rv-stage");
  stage.innerHTML = h
    ? `${h.is_print ? `<span class="starred-tag">★ In ${escapeHtml(dbName)}</span>` : ""}
       <img id="rv-hero-img" src="/api/p/${slug}/image/${h.id}" alt="" draggable="false">
       <svg class="rv-face-svg" id="rv-face-svg" aria-hidden="true"></svg>
       <div class="rv-face-layer" id="rv-face-layer"></div>
       <div class="rv-face-pop hidden" id="rv-face-pop"></div>
       <span class="zoom-badge" id="rv-zoom-badge"></span>`
    : `<div class="empty-stage">—</div>`;
  applyZoom();
  renderFaceChips();

  // star button → toggles the default bucket
  const starBtn = document.getElementById("rv-star");
  starBtn.innerHTML = h && h.is_print ? `★ In ${escapeHtml(dbName)}` : `☆ Add to ${escapeHtml(dbName)}`;
  starBtn.classList.toggle("accent", !!(h && h.is_print));

  // filmstrip — STABLE capture order; featured highlighted in place (no hoisting)
  document.getElementById("rv-strip").innerHTML = frames
    .map((f) => {
      const chips =
        (byImg[f.id] || []).map((p) => `<span class="ftag crit ${p.source}">${META[p.t].label}</span>`).join("") +
        (f.is_print ? `<span class="ftag print">★ ${escapeHtml(dbName)}</span>` : "");
      const bdots = [...(imgBuckets[f.id] || [])]
        .map((bid) => {
          const b = buckets.find((x) => x.id === bid);
          return b ? `<span class="bk-dot" style="background:${escapeHtml(b.color || "#cda35c")}"></span>` : "";
        })
        .join("");
      const alt = `Frame, print score ${pct(f.print_score)}${f.is_print ? ", in print list" : ""}`;
      return `<div class="frame-thumb ${f.id === heroId ? "cur" : ""} ${f.is_print ? "star" : ""}" data-id="${f.id}"
        role="button" tabindex="0" aria-label="${alt}" aria-pressed="${f.id === heroId}">
        <img loading="lazy" src="/api/p/${slug}/image_thumb/${f.id}" alt="${alt}">
        <div class="tags">${chips}</div>${bdots ? `<div class="bk-dots">${bdots}</div>` : ""}</div>`;
    })
    .join("");
  document.querySelectorAll("#rv-strip .frame-thumb").forEach((el) => {
    const activate = (e) => {
      const id = +el.dataset.id;
      if (e && e.shiftKey) {
        rangeStar(id);
        return;
      }
      selectHero(id);
    };
    el.onclick = activate;
    el.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        activate(e);
      }
    };
  });

  renderBucketStrip();
  renderInspector();
}

function selectHero(id) {
  if (id === heroId) return;
  heroId = id;
  resetZoom();
  render();
  scrollHeroIntoView();
  loadFaces(slug, pos);
}

function scrollHeroIntoView() {
  const cur = document.querySelector(`#rv-strip .frame-thumb[data-id="${heroId}"]`);
  if (cur) cur.scrollIntoView({ block: "nearest", inline: "center" });
}

function updateProgress() {
  const bar = document.getElementById("rv-progress");
  if (!bar) return;
  if (activeFilter) {
    const i = frames.findIndex((f) => f.id === heroId);
    bar.style.width = `${frames.length ? ((i + 1) / frames.length) * 100 : 0}%`;
    return;
  }
  const denom = total || series.length || 1;
  bar.style.width = `${(reviewed.size / denom) * 100}%`;
}

// ---- inspector: per-person stats + auto-pick feedback ----
function renderInspector() {
  const el = document.getElementById("rv-inspector");
  if (!el || !layout.inspOpen) return;
  const h = hero();
  if (!h) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `
    <div class="insp-toolbar">
      <button id="insp-flip" class="insp-tool" title="Move the panel to the other side">⇄ move</button>
      <button id="insp-hide" class="insp-tool" title="Hide the panel (I)">✕ hide</button>
    </div>
    <div class="insp-sec">
      <div class="insp-head">In buckets <span class="insp-sub">where it lands</span></div>
      ${bucketMembership(h)}
    </div>
    <div class="insp-sec">
      <div class="insp-head">Frame quality <b>${faces.length ? `${faces.length} 𝍌` : ""}</b></div>
      ${fracChips(h)}
      ${lightFlags(h)}
      <div class="insp-bars">
        ${qbar("Group / print", h.print_score)}
        ${qbar("Moment", h.moment_score)}
        ${qbar("Composition", h.comp_score)}
        ${qbar("Sharpness", h.global_sharpness)}
        ${qbar("Exposure", h.exposure_score)}
      </div>
    </div>
    ${
      activeFilter
        ? ""
        : `<details class="insp-sec insp-fb" ${fbOpen ? "open" : ""}>
      <summary class="insp-head">Was the pick right? <span class="insp-sub">trains the scorer</span></summary>
      ${ORDER.map(feedbackRow).join("")}
      <button class="btn ghost tiny" id="fb-export" title="Download all feedback as JSON">Export feedback ↓</button>
    </details>`
    }`;

  el.querySelectorAll(".insp-face").forEach((row) => {
    row.onclick = () => openFaceModal(slug, +row.dataset.fid);
  });
  el.querySelectorAll(".ibk").forEach((chip) => {
    chip.onclick = () => {
      const b = buckets.find((x) => x.id === +chip.dataset.bid);
      if (b) toggleBucket(b, h.id);
    };
  });
  const fb = el.querySelector(".insp-fb");
  if (fb) fb.ontoggle = () => (fbOpen = fb.open); // remember collapsed/expanded across re-renders
  el.querySelectorAll("[data-fb]").forEach((b) => {
    b.onclick = () => onFeedback(b.dataset.fb, b.dataset.act);
  });
  const exp = el.querySelector("#fb-export");
  if (exp) exp.onclick = exportFeedback;
  const flip = el.querySelector("#insp-flip");
  if (flip) flip.onclick = flipInspectorSide;
  const hide = el.querySelector("#insp-hide");
  if (hide) hide.onclick = toggleInspector;
}

function flipInspectorSide() {
  layout.inspSide = layout.inspSide === "left" ? "right" : "left";
  applyLayout();
  saveLayout();
}

// ===================== floating face overlay =====================
// Faces float as boxes over the photo. Hover one → its stats + a leader line to
// where that person is in the frame + a rename CTA. No fixed faces panel.
function personName(f) {
  return f.display_name || (f.person_id >= 0 ? `Person ${f.person_id}` : "Ungrouped");
}

function renderFaceChips() {
  const layer = document.getElementById("rv-face-layer");
  if (!layer) return;
  hideFacePop();
  faceIdx = -1;
  layer.innerHTML = faces
    .map(
      (f, i) =>
        `<button class="rv-face-chip" data-i="${i}" aria-label="${escapeHtml(personName(f))} — hover for stats">
           <img loading="lazy" src="/api/p/${slug}/thumb/${f.id}" alt="">
           <span class="rv-face-chip-name">${escapeHtml(personName(f))}</span>
         </button>`,
    )
    .join("");
  layer.querySelectorAll(".rv-face-chip").forEach((chip) => {
    const f = faces[+chip.dataset.i];
    chip.addEventListener("mouseenter", () => showFacePop(f, chip));
    chip.addEventListener("focus", () => showFacePop(f, chip));
    chip.addEventListener("mouseleave", scheduleHidePop);
    chip.addEventListener("blur", scheduleHidePop);
  });
}

// bbox is in original-image pixels; the <img> rect already carries the zoom/pan
// transform, so (bbox / imgDims) × imgRect lands on the right spot at any zoom.
function faceScreenBox(f) {
  const img = document.getElementById("rv-hero-img");
  const stage = document.getElementById("rv-stage");
  if (!img || !stage) return null;
  const r = img.getBoundingClientRect();
  const s = stage.getBoundingClientRect();
  const w = f.img_w || 1,
    h = f.img_h || 1;
  return {
    x1: r.left - s.left + (f.bbox_x1 / w) * r.width,
    y1: r.top - s.top + (f.bbox_y1 / h) * r.height,
    x2: r.left - s.left + (f.bbox_x2 / w) * r.width,
    y2: r.top - s.top + (f.bbox_y2 / h) * r.height,
  };
}

let popHideTimer = null;
function scheduleHidePop() {
  clearTimeout(popHideTimer);
  popHideTimer = setTimeout(hideFacePop, 180);
}
function cancelHidePop() {
  clearTimeout(popHideTimer);
}

function showFacePop(f, chip) {
  cancelHidePop();
  activeFace = { f, chip };
  drawLeader(f, chip);
  const pop = document.getElementById("rv-face-pop");
  if (!pop) return;
  const named = f.person_id >= 0;
  pop.innerHTML = `
    <div class="fp-head">
      <img src="/api/p/${slug}/thumb/${f.id}" alt="">
      <input class="fp-name" id="fp-name" value="${escapeHtml(personName(f))}" ${named ? "" : "disabled"}
        spellcheck="false" title="${named ? "Rename this person — Enter to save" : "Ungrouped — open detail to assign"}">
    </div>
    <div class="fp-bars">
      ${mini("eyes", f.eye_open)} ${mini("smile", f.smile)} ${mini("front", f.frontality)} ${mini("sharp", f.face_sharpness)}
    </div>
    <button class="fp-btn" id="fp-detail">Reassign / detail…</button>`;
  const stage = document.getElementById("rv-stage").getBoundingClientRect();
  const cr = chip.getBoundingClientRect();
  pop.classList.remove("hidden");
  const pw = pop.offsetWidth || 240,
    ph = pop.offsetHeight || 150;
  let left = cr.right - stage.left + 12;
  if (left + pw > stage.width - 6) left = cr.left - stage.left - pw - 12;
  if (left < 6) left = 6;
  const top = Math.max(6, Math.min(stage.height - ph - 6, cr.top - stage.top));
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
  pop.onmouseenter = cancelHidePop;
  pop.onmouseleave = scheduleHidePop;
  const nameInput = pop.querySelector("#fp-name");
  if (nameInput && named) {
    nameInput.onkeydown = (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        renamePerson(f, nameInput.value);
        nameInput.blur();
      }
    };
  }
  const detail = pop.querySelector("#fp-detail");
  if (detail) detail.onclick = () => openFaceModal(slug, f.id);
}

function drawLeader(f, chip) {
  const svg = document.getElementById("rv-face-svg");
  const box = faceScreenBox(f);
  if (!svg || !box) return;
  const stage = document.getElementById("rv-stage").getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${Math.round(stage.width)} ${Math.round(stage.height)}`);
  const cr = chip.getBoundingClientRect();
  const cx = cr.left - stage.left + cr.width / 2;
  const cy = cr.top - stage.top + cr.height / 2;
  const bx = (box.x1 + box.x2) / 2;
  const by = (box.y1 + box.y2) / 2;
  svg.innerHTML = `
    <line x1="${cx}" y1="${cy}" x2="${bx}" y2="${by}" class="rv-face-line"></line>
    <rect x="${box.x1}" y="${box.y1}" width="${Math.max(0, box.x2 - box.x1)}" height="${Math.max(0, box.y2 - box.y1)}"
      rx="4" class="rv-face-box"></rect>
    <circle cx="${cx}" cy="${cy}" r="3.5" class="rv-face-dot"></circle>`;
  svg.classList.add("on");
}

function hideFacePop() {
  activeFace = null;
  const svg = document.getElementById("rv-face-svg");
  if (svg) {
    svg.classList.remove("on");
    svg.innerHTML = "";
  }
  const pop = document.getElementById("rv-face-pop");
  if (pop) pop.classList.add("hidden");
}

function redrawActiveFace() {
  if (activeFace && activeFace.chip.isConnected) drawLeader(activeFace.f, activeFace.chip);
  else if (activeFace) hideFacePop();
}

// keyboard face selection: Tab / Shift+Tab cycle the floating chips
function cycleFace(d) {
  if (!faces.length) return false;
  faceIdx = (faceIdx + d + faces.length) % faces.length;
  const chip = document.querySelectorAll("#rv-face-layer .rv-face-chip")[faceIdx];
  if (chip) {
    chip.focus({ preventScroll: true });
    showFacePop(faces[faceIdx], chip);
  }
  return true;
}
function focusRenameActive() {
  if (!activeFace) cycleFace(1); // R with nothing selected → grab the first face
  const input = document.getElementById("fp-name");
  if (input && !input.disabled) input.focus({ preventScroll: true });
  else if (input) toast("Ungrouped face — use Reassign / detail to assign");
}

async function renamePerson(f, name) {
  name = (name || "").trim();
  if (!name || name === personName(f)) return;
  try {
    await post(`/api/p/${slug}/persons/${f.person_id}/rename`, { name });
    faces.forEach((x) => x.person_id === f.person_id && (x.display_name = name));
    renderFaceChips();
    toast(`Renamed to ${name}`);
    window.dispatchEvent(new CustomEvent("atelier:people-changed"));
  } catch {
    toast("Could not rename", true);
  }
}

function mini(label, v) {
  const low = (v || 0) < 0.45;
  return `<span class="mini ${low ? "low" : ""}" title="${label} ${pct(v)}">
    <i style="width:${Math.round((v || 0) * 100)}%"></i><em>${label}</em></span>`;
}
function qbar(label, v) {
  return `<div class="qrow"><span>${label}</span>
    <div class="qtrack"><i style="width:${Math.round((v || 0) * 100)}%"></i></div>
    <b>${pct(v)}</b></div>`;
}

function defaultBucket() {
  return buckets.find((b) => b.is_default) || buckets.find((b) => b.role === "print") || buckets[0];
}

// reflect server is_print (= default-bucket membership) into imgBuckets so the ★ and the
// inspector chip agree before the /buckets/for-images round-trip refines the full set.
function seedDefaultMembership() {
  const db = defaultBucket();
  if (!db) return;
  frames.forEach((f) => {
    if (f.is_print) (imgBuckets[f.id] || (imgBuckets[f.id] = new Set())).add(db.id);
  });
}

// the inspector "where it lands" chips — every bucket, filled when the hero is in it,
// the default (spacebar / print) marked with a ★. Click toggles membership.
function bucketMembership(h) {
  if (!buckets.length) return `<p class="insp-empty">No buckets — create some in the Buckets tab.</p>`;
  const inSet = imgBuckets[h.id] || new Set();
  const chips = buckets
    .map(
      (b) =>
        `<button class="ibk ${inSet.has(b.id) ? "on" : ""} ${b.is_default ? "def" : ""}" data-bid="${b.id}"
          style="--bc:${escapeHtml(b.color || "#cda35c")}">${b.is_default ? "★ " : ""}${escapeHtml(b.name)}</button>`,
    )
    .join("");
  return `<div class="insp-bk-chips">${chips}</div>
    <p class="insp-bk-hint">Space → ${escapeHtml((defaultBucket() || {}).name || "default")} · 1–9 quick-tag</p>`;
}

// plain-language "everyone" tags: X/N eyes-open / smiling / facing
function fracChips(h) {
  const n = h.face_count || 0;
  if (!n) return "";
  const c = (frac) => (frac == null ? "–" : `${Math.round(frac * n)}/${n}`);
  const low = (frac) => frac != null && frac < 0.999;
  return `<div class="insp-fracs">
    <span class="frac ${low(h.eyes_open_frac) ? "warn" : ""}">${c(h.eyes_open_frac)} eyes open</span>
    <span class="frac">${c(h.smile_frac)} smiling</span>
    <span class="frac">${c(h.front_frac)} facing</span>
    ${h.gaze_frac != null ? `<span class="frac">${c(h.gaze_frac)} eye contact</span>` : ""}
  </div>`;
}

// light / colour / focus flags — surface ONLY what's actually a problem (plus bokeh
// as a positive). Thresholds mirror config.py (HIGHLIGHT_WARN / SHADOW_WARN / …).
function lightFlags(h) {
  const f = [];
  const bad = (v, t) => v != null && v > t;
  if (bad(h.highlight_frac, 0.08)) f.push(`<span class="flag warn">blown highlights</span>`);
  if (bad(h.shadow_frac, 0.18)) f.push(`<span class="flag warn">crushed shadows</span>`);
  if (bad(h.color_cast, 0.5)) f.push(`<span class="flag warn">colour cast</span>`);
  if (bad(h.horizon_tilt, 0.5)) f.push(`<span class="flag warn">tilted</span>`);
  if (h.skin_exposure != null && h.skin_exposure < 0.4) f.push(`<span class="flag warn">dim subject</span>`);
  if (bad(h.bokeh, 0.65)) f.push(`<span class="flag good">bokeh</span>`);
  return f.length ? `<div class="insp-flags">${f.join("")}</div>` : "";
}

function feedbackRow(ptype) {
  const p = picks[ptype];
  const fb = feedback[ptype] || {};
  const better = fb.better_image_id;
  return `<div class="fb-row ${fb.verdict ? "rated" : ""}" data-row="${ptype}">
    <span class="fb-label crit">${META[ptype].label}</span>
    <span class="fb-frame">${p ? `frame ${frameNo(p.image_id)}` : "—"}${p && p.source === "manual" ? " (manual)" : ""}</span>
    <span class="fb-acts">
      <button class="fb-btn good ${fb.verdict === "good" ? "on" : ""}" data-fb="${ptype}" data-act="good" title="Good pick">👍</button>
      <button class="fb-btn bad ${fb.verdict === "bad" ? "on" : ""}" data-fb="${ptype}" data-act="bad" title="Wrong pick">👎</button>
      <button class="fb-btn ${better === heroId ? "on" : ""}" data-fb="${ptype}" data-act="better"
        title="The frame I'm looking at is the better ${META[ptype].label.toLowerCase()}">＋ this</button>
    </span>
    ${better ? `<span class="fb-better">better → frame ${frameNo(better)}</span>` : ""}
  </div>`;
}
function frameNo(iid) {
  const i = frames.findIndex((f) => f.id === iid);
  return i >= 0 ? i + 1 : "?";
}

async function onFeedback(ptype, act) {
  const p = picks[ptype];
  if (!p) return;
  const cur = feedback[ptype] || {};
  let body;
  if (act === "better") {
    body = { pick_type: ptype, auto_image_id: p.image_id, verdict: cur.verdict || "bad", better_image_id: heroId };
  } else {
    // toggle the verdict off if re-clicking the same one
    const verdict = cur.verdict === act ? null : act;
    body = { pick_type: ptype, auto_image_id: p.image_id, verdict, better_image_id: cur.better_image_id };
  }
  try {
    const r = await post(`/api/p/${slug}/feedback`, body);
    if (r.cleared) delete feedback[ptype];
    else feedback[ptype] = { verdict: body.verdict, better_image_id: body.better_image_id };
    toast(
      act === "better" ? `Marked frame ${frameNo(heroId)} as better ${META[ptype].label}` : "Thanks — feedback saved",
    );
    renderInspector();
  } catch {
    toast("Could not save feedback", true);
  }
}

async function exportFeedback() {
  try {
    const d = await api(`/api/p/${slug}/feedback/export`);
    const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${slug}-pick-feedback.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast(`Exported ${d.count} feedback record${d.count === 1 ? "" : "s"}`);
  } catch {
    toast("Could not export feedback", true);
  }
}

function renderBucketStrip() {
  const el = document.getElementById("rv-buckets");
  if (!el) return;
  if (!buckets.length) {
    el.innerHTML = `<span class="bucket-hint">No buckets yet — create them in the Buckets tab, then press 1–9 here.</span>`;
    return;
  }
  const h = hero();
  const inSet = (h && imgBuckets[h.id]) || new Set();
  el.innerHTML = buckets
    .map(
      (b, i) =>
        `<button class="bk-chip ${inSet.has(b.id) ? "on" : ""}" data-id="${b.id}" style="--bc:${escapeHtml(b.color || "#cda35c")}">
           <span class="k">${i < 9 ? i + 1 : "•"}</span>${b.is_default ? "★ " : ""}${escapeHtml(b.name)}</button>`,
    )
    .join("");
  el.querySelectorAll(".bk-chip").forEach((c) => {
    c.onclick = () => {
      const b = buckets.find((x) => x.id === +c.dataset.id);
      const h2 = hero();
      if (b && h2) toggleBucket(b, h2.id);
    };
  });
}

async function toggleBucket(b, imageId) {
  try {
    const r = await post(`/api/p/${slug}/buckets/${b.id}/toggle`, { image_id: imageId });
    const set = imgBuckets[imageId] || (imgBuckets[imageId] = new Set());
    if (r.in) set.add(b.id);
    else set.delete(b.id);
    b.count += r.in ? 1 : -1;
    if (b.is_default) {
      // the default bucket IS the print list — keep the ★ / star button in sync
      const f = frames.find((x) => x.id === imageId);
      if (f) f.is_print = r.in;
    }
    toast(`${r.in ? "Added to" : "Removed from"} ${b.name}`);
    render();
  } catch {
    toast("Could not update bucket", true);
  }
}

function toggleBucketForHero(idx) {
  const b = buckets[idx];
  const h = hero();
  if (b && h) toggleBucket(b, h.id);
}

// Star every frame from the current hero up to (and including) the clicked frame.
async function rangeStar(targetId) {
  let a = frames.findIndex((f) => f.id === heroId);
  let b = frames.findIndex((f) => f.id === targetId);
  if (a < 0 || b < 0) return;
  if (a > b) [a, b] = [b, a];
  const slice = frames.slice(a, b + 1);
  const ids = slice.filter((f) => !f.is_print).map((f) => f.id);
  if (!ids.length) {
    toast("Already in print list");
    return;
  }
  let ok = false;
  try {
    await post(`/api/p/${slug}/star_many`, { image_ids: ids });
    ok = true;
  } catch {
    for (const id of ids) {
      try {
        await post(`/api/p/${slug}/star/${id}`, {});
        ok = true;
      } catch {}
    }
  }
  if (!ok) {
    toast("Could not star range", true);
    return;
  }
  const db = defaultBucket();
  slice.forEach((f) => {
    f.is_print = true;
    if (db) (imgBuckets[f.id] || (imgBuckets[f.id] = new Set())).add(db.id);
  });
  if (db) db.count += ids.length;
  toast(`Added ${ids.length} frame${ids.length > 1 ? "s" : ""} to ${db ? db.name : "print list"}`);
  render();
}

async function starRecommended() {
  const recId = picks.group && picks.group.image_id;
  if (!recId) {
    toast("No recommended frame for this burst", true);
    return;
  }
  const f = frames.find((x) => x.id === recId);
  if (f && f.is_print) {
    toast("Recommended frame already in print list");
    return;
  }
  try {
    const r = await post(`/api/p/${slug}/star/${recId}`, {});
    if (f) f.is_print = r.starred;
    toast(r.starred ? "Starred recommended frame" : "Removed recommended frame");
    render();
  } catch {
    toast("Could not star recommended frame", true);
  }
}

async function star() {
  const h = hero();
  if (!h) return;
  const r = await post(`/api/p/${slug}/star/${h.id}`, {});
  h.is_print = r.starred;
  const db = defaultBucket();
  if (db) {
    const set = imgBuckets[h.id] || (imgBuckets[h.id] = new Set());
    if (r.starred) set.add(db.id);
    else set.delete(db.id);
    db.count += r.starred ? 1 : -1;
  }
  const nm = db ? db.name : "print list";
  toast(r.starred ? `Added to ${nm}` : `Removed from ${nm}`);
  render();
}

async function setCriterion(t) {
  const h = hero();
  if (!h) return;
  if (activeFilter) return; // criteria are per-burst; not applicable to a filtered set
  await post(`/api/p/${slug}/series/${series[pos].id}/pick`, { pick_type: t, image_id: h.id });
  picks[t] = { image_id: h.id, source: "manual" };
  byImg = {};
  ORDER.forEach((k) => {
    const p = picks[k];
    if (p) (byImg[p.image_id] = byImg[p.image_id] || []).push({ t: k, source: p.source });
  });
  toast(`${META[t].label} → this frame`);
  render();
}

// ---- mark reviewed (server-backed; drives the progress bar) ----
function markReviewed(sid) {
  if (reviewed.has(sid)) return;
  reviewed.add(sid);
  updateProgress();
  post(`/api/p/${slug}/series/${sid}/reviewed`, { reviewed: true }).catch(() => reviewed.delete(sid));
}

function exitFilter() {
  activeFilter = null;
  series = [];
  total = 0;
  pos = 0;
  hideFacePop();
  document.querySelector(".rv-sort")?.classList.remove("hidden");
  loadSeries();
}

// ===================== navigation =====================
async function step(d) {
  if (activeFilter) return moveHero(d); // filter view is one flat set — ←→ steps photos
  if (!series.length) return;
  if (series[pos]) markReviewed(series[pos].id); // leaving a burst = reviewed
  pos = (pos + d + series.length) % series.length;
  lsSet(posKey(), pos);
  await load();
}

function moveHero(d) {
  if (!frames.length) return;
  let i = frames.findIndex((f) => f.id === heroId);
  i = (i + d + frames.length) % frames.length;
  selectHero(frames[i].id);
}

// ===================== zoom / pan (works in fullscreen) =====================
function resetZoom() {
  zoom.scale = 1;
  zoom.tx = 0;
  zoom.ty = 0;
}
function applyZoom() {
  const img = document.getElementById("rv-hero-img");
  if (!img) return;
  img.style.transform = `translate(${zoom.tx}px, ${zoom.ty}px) scale(${zoom.scale})`;
  img.style.cursor = zoom.scale > 1 ? (zoom.panning ? "grabbing" : "grab") : "zoom-in";
  const badge = document.getElementById("rv-zoom-badge");
  if (badge) badge.textContent = zoom.scale > 1.01 ? `${Math.round(zoom.scale * 100)}%` : "";
  redrawActiveFace(); // keep a hovered leader line glued to the face through zoom/pan
}
function clampPan() {
  const stage = document.getElementById("rv-stage");
  if (!stage) return;
  const r = stage.getBoundingClientRect();
  const maxX = (r.width * (zoom.scale - 1)) / 2;
  const maxY = (r.height * (zoom.scale - 1)) / 2;
  zoom.tx = Math.max(-maxX, Math.min(maxX, zoom.tx));
  zoom.ty = Math.max(-maxY, Math.min(maxY, zoom.ty));
}
function zoomAt(clientX, clientY, factor) {
  const stage = document.getElementById("rv-stage");
  if (!stage) return;
  const r = stage.getBoundingClientRect();
  const cx = clientX - r.left - r.width / 2;
  const cy = clientY - r.top - r.height / 2;
  const ns = Math.max(1, Math.min(8, zoom.scale * factor));
  // keep the point under the cursor fixed
  zoom.tx = cx - ((cx - zoom.tx) / zoom.scale) * ns;
  zoom.ty = cy - ((cy - zoom.ty) / zoom.scale) * ns;
  zoom.scale = ns;
  if (zoom.scale <= 1.001) resetZoom();
  clampPan();
  applyZoom();
}
function toggleZoom(clientX, clientY) {
  const stage = document.getElementById("rv-stage");
  if (!stage) return;
  const r = stage.getBoundingClientRect();
  if (zoom.scale > 1.01) resetZoom();
  else {
    zoom.scale = 2.5;
    const cx = (clientX ?? r.left + r.width / 2) - r.left - r.width / 2;
    const cy = (clientY ?? r.top + r.height / 2) - r.top - r.height / 2;
    zoom.tx = -cx * (zoom.scale - 1);
    zoom.ty = -cy * (zoom.scale - 1);
    clampPan();
  }
  applyZoom();
}

function wireStageZoom() {
  const stage = document.getElementById("rv-stage");
  if (!stage || stage.dataset.zoomWired) return;
  stage.dataset.zoomWired = "1";
  stage.addEventListener(
    "wheel",
    (e) => {
      if (!document.getElementById("rv-hero-img")) return;
      e.preventDefault();
      // Gentle, delta-proportional zoom. ctrlKey === trackpad pinch (smaller, denser
      // deltas) gets a lower gain than a mouse wheel; each event is capped to a small
      // step so a fast flick / hard pinch doesn't snap across the whole range.
      const gain = e.ctrlKey ? 0.0042 : 0.0011;
      let factor = Math.exp(-e.deltaY * gain);
      factor = Math.max(0.92, Math.min(1.085, factor));
      zoomAt(e.clientX, e.clientY, factor);
    },
    { passive: false },
  );
  stage.addEventListener("dblclick", (e) => {
    e.preventDefault();
    toggleZoom(e.clientX, e.clientY);
  });
  stage.addEventListener("pointerdown", (e) => {
    if (zoom.scale <= 1) return;
    zoom.panning = true;
    zoom.sx = e.clientX - zoom.tx;
    zoom.sy = e.clientY - zoom.ty;
    stage.setPointerCapture(e.pointerId);
    applyZoom();
  });
  stage.addEventListener("pointermove", (e) => {
    if (!zoom.panning) return;
    zoom.tx = e.clientX - zoom.sx;
    zoom.ty = e.clientY - zoom.sy;
    clampPan();
    applyZoom();
  });
  const end = (e) => {
    if (!zoom.panning) return;
    zoom.panning = false;
    try {
      document.getElementById("rv-stage").releasePointerCapture(e.pointerId);
    } catch {}
    applyZoom();
  };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", end);
}

// ===================== layout: resize / move / collapse =====================
function applyLayout() {
  const sec = document.getElementById("view-review");
  if (!sec) return;
  sec.style.setProperty("--rv-insp-w", `${layout.inspW}px`);
  sec.style.setProperty("--rv-strip-h", `${layout.stripH}px`);
  sec.classList.toggle("insp-hidden", !layout.inspOpen);
  sec.classList.toggle("insp-left", layout.inspSide === "left");
}
function saveLayout() {
  lsSet(LAYOUT_KEY, layout);
}

function wireResizers() {
  const splitX = document.getElementById("rv-split-x");
  const splitY = document.getElementById("rv-split-y");
  if (splitX && !splitX.dataset.wired) {
    splitX.dataset.wired = "1";
    dragResize(splitX, (dx) => {
      const sign = layout.inspSide === "left" ? 1 : -1;
      layout.inspW = Math.max(220, Math.min(620, layout.inspW + sign * dx));
      applyLayout();
    });
  }
  if (splitY && !splitY.dataset.wired) {
    splitY.dataset.wired = "1";
    dragResize(splitY, (_dx, dy) => {
      layout.stripH = Math.max(90, Math.min(420, layout.stripH - dy));
      applyLayout();
    });
  }
}
// delta-based drag (layout-independent); commits to localStorage on release.
function dragResize(handle, onDelta) {
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const x0 = e.clientX,
      y0 = e.clientY;
    handle.setPointerCapture(e.pointerId);
    handle.classList.add("dragging");
    // re-anchor each tick so deltas are incremental, not absolute
    let lastX = x0,
      lastY = y0;
    const onMove = (ev) => {
      onDelta(ev.clientX - lastX, ev.clientY - lastY, ev);
      lastX = ev.clientX;
      lastY = ev.clientY;
    };
    const up = (ev) => {
      handle.releasePointerCapture(ev.pointerId);
      handle.classList.remove("dragging");
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      saveLayout();
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  });
}

function toggleInspector() {
  layout.inspOpen = !layout.inspOpen;
  applyLayout();
  saveLayout();
  if (layout.inspOpen) renderInspector();
}

// ===================== chrome wiring =====================
function wireChrome() {
  document.getElementById("rv-prev").onclick = () => step(-1);
  document.getElementById("rv-next").onclick = () => step(1);
  document.getElementById("rv-star").onclick = star;
  const rec = document.getElementById("rv-star-rec");
  if (rec) rec.onclick = starRecommended;
  document.getElementById("rv-fs").onclick = toggleFullscreen;
  const it = document.getElementById("rv-insp-toggle");
  if (it) it.onclick = toggleInspector;
  wireStageZoom();
  wireResizers();
  if (!window.__rvResizeWired) {
    window.__rvResizeWired = true;
    window.addEventListener("resize", redrawActiveFace);
    document.addEventListener("fullscreenchange", () => requestAnimationFrame(redrawActiveFace));
  }
}

function toggleFullscreen() {
  const el = document.getElementById("view-review");
  if (!document.fullscreenElement) (el.requestFullscreen || el.webkitRequestFullscreen).call(el);
  else document.exitFullscreen();
}

function onKey(e) {
  // only Review is mounted; ignore while a modal is open
  if (document.querySelector(".modal:not(.hidden)")) return;
  if (document.getElementById("view-review").classList.contains("hidden")) return;
  const tag = (e.target && e.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return; // don't hijack typing
  const k = e.key;
  if (k === "Tab") {
    if (!faces.length) return; // nothing to cycle → leave native Tab alone
    e.preventDefault();
    cycleFace(e.shiftKey ? -1 : 1);
  } else if (k === "Escape") {
    if (activeFace) {
      hideFacePop();
      faceIdx = -1;
    }
  } else if (k === "ArrowLeft") {
    e.preventDefault();
    step(-1);
  } else if (k === "ArrowRight" || k === "x" || k === "X") {
    e.preventDefault();
    step(1);
  } else if (k === "ArrowUp") {
    e.preventDefault();
    moveHero(-1);
  } else if (k === "ArrowDown") {
    e.preventDefault();
    moveHero(1);
  } else if (k === "f" || k === "F") toggleFullscreen();
  else if (k === "i" || k === "I") toggleInspector();
  else if (k === "r" || k === "R") {
    e.preventDefault();
    focusRenameActive();
  } else if (k === "z" || k === "Z" || k === "Enter") {
    e.preventDefault();
    toggleZoom();
  } else if (k === " " || k === "Spacebar" || k === "s" || k === "S") {
    e.preventDefault();
    star();
  } else if (k >= "1" && k <= "9") {
    e.preventDefault();
    toggleBucketForHero(+k - 1);
  } else if (k === "g" || k === "G") setCriterion("group");
  else if (k === "c" || k === "C") setCriterion("candid");
  else if (k === "a" || k === "A") setCriterion("aesthetic");
}
