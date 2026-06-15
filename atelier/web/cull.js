// Review / cull: step through bursts, see the recommended frame, star keepers, bucket frames.
import { api, post, pct, escapeHtml, toast } from "./api.js";
import { openLightbox } from "./faces.js";

const META = {
  group: { label: "Everyone", desc: "Everyone looking good — eyes open, sharp." },
  candid: { label: "Candid", desc: "Natural, un-posed — a real moment." },
  aesthetic: { label: "Striking", desc: "Most visually striking frame." },
};
const ORDER = ["group", "candid", "aesthetic"];

let slug = null;
let series = []; // [{id, frame_count}]
let pos = 0;
let frames = []; // current burst frames (server order, by print_score)
let displayFrames = []; // filmstrip order (featured first) — frozen per burst in load()
let byImg = {}; // image_id -> [{pick_type, source}] for tag chips
let picks = {}; // pick_type -> {image_id, source}
let heroId = null;
let keyHandler = null;
let buckets = []; // project buckets — the Review strip + number-key shortcuts
let imgBuckets = {}; // image_id -> Set(bucket_id) for the current burst's frames

export async function mountReview(s) {
  slug = s;
  series = [];
  let off = 0;
  while (true) {
    const r = await api(`/api/p/${slug}/series?offset=${off}&limit=200`);
    series.push(...(r.items || []));
    if (r.next_offset == null) break;
    off = r.next_offset;
  }
  buckets = await api(`/api/p/${slug}/buckets`).catch(() => []);
  if (!keyHandler) {
    keyHandler = onKey;
    window.addEventListener("keydown", keyHandler);
  }
  document.getElementById("rv-prev").onclick = () => step(-1);
  document.getElementById("rv-next").onclick = () => step(1);
  document.getElementById("rv-star").onclick = star;
  document.getElementById("rv-star-rec").onclick = starRecommended;
  document.getElementById("rv-fs").onclick = toggleFullscreen;

  if (!series.length) {
    document.getElementById("rv-stage").innerHTML = `<div class="empty-stage">No multi-frame bursts to review.</div>`;
    document.getElementById("rv-strip").innerHTML = "";
    document.getElementById("rv-count").textContent = "—";
    return;
  }
  pos = Math.min(pos, series.length - 1);
  await load();
}

export function unmountReview() {
  if (keyHandler) {
    window.removeEventListener("keydown", keyHandler);
    keyHandler = null;
  }
}

async function load() {
  const sid = series[pos].id;
  const mySlug = slug,
    myPos = pos; // snapshot: a different project/burst may mount mid-fetch
  const [fr, pk] = await Promise.all([
    api(`/api/p/${slug}/series/${sid}/images`),
    api(`/api/p/${slug}/series/${sid}/picks`).then((d) => {
      const m = {};
      (d.picks || []).forEach((p) => {
        m[p.pick_type] = { image_id: p.image_id, source: p.source };
      });
      return m;
    }),
  ]);
  if (slug !== mySlug || pos !== myPos) return; // navigated away — don't render stale data
  frames = fr;
  picks = pk;
  heroId = (picks.group && picks.group.image_id) || (frames[0] && frames[0].id);
  // Freeze the filmstrip order ONCE per burst (suggested/starred first). Starring
  // later must not reorder — that's what was bouncing you back to the start.
  byImg = {};
  ORDER.forEach((t) => {
    const p = picks[t];
    if (p) (byImg[p.image_id] = byImg[p.image_id] || []).push({ t, source: p.source });
  });
  const featured = (f) => byImg[f.id] || f.is_print;
  displayFrames = [...frames.filter(featured), ...frames.filter((f) => !featured(f))];
  imgBuckets = {};
  render(); // paint the photo + strip immediately — don't block on the membership round-trip
  // then fetch which buckets each frame is in and re-render to add the coloured dots
  const ids = frames.map((f) => f.id).join(",");
  if (ids && buckets.length) {
    const mem = await api(`/api/p/${slug}/buckets/for-images?ids=${ids}`).catch(() => ({}));
    if (slug !== mySlug || pos !== myPos) return;
    Object.entries(mem).forEach(([iid, arr]) => {
      imgBuckets[+iid] = new Set(arr);
    });
    render();
  }
}

function hero() {
  return frames.find((f) => f.id === heroId) || frames[0];
}

function render() {
  const h = hero();
  document.getElementById("rv-count").textContent = `Burst ${pos + 1} of ${series.length} · ${frames.length} frames`;
  document.getElementById("rv-progress").style.width = `${((pos + 1) / series.length) * 100}%`;

  // stage
  document.getElementById("rv-stage").innerHTML = h
    ? `${h.is_print ? `<span class="starred-tag">★ In print list</span>` : ""}
       <img src="/api/p/${slug}/image/${h.id}" alt="">`
    : `<div class="empty-stage">—</div>`;
  document.getElementById("rv-stage").onclick = () => {
    const seq = displayFrames.length ? displayFrames : frames;
    if (h)
      openLightbox(
        seq.map((f) => ({ src: `/api/p/${slug}/image/${f.id}`, cap: `print ${pct(f.print_score)}` })),
        seq.findIndex((f) => f.id === h.id),
      );
  };

  // star button label
  const starBtn = document.getElementById("rv-star");
  starBtn.innerHTML = h && h.is_print ? "★ In print list" : "☆ Add to print list";
  starBtn.classList.toggle("accent", !!(h && h.is_print));

  // filmstrip — order is frozen in load(); render only refreshes tags/highlight in place
  document.getElementById("rv-strip").innerHTML = displayFrames
    .map((f) => {
      const chips =
        (byImg[f.id] || []).map((p) => `<span class="ftag crit ${p.source}">${META[p.t].label}</span>`).join("") +
        (f.is_print ? `<span class="ftag print">★ Print</span>` : "");
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
      heroId = id;
      render();
      const cur = document.querySelector(`#rv-strip .frame-thumb[data-id="${heroId}"]`);
      if (cur) cur.scrollIntoView({ block: "nearest", inline: "center" });
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
           <span class="k">${i < 9 ? i + 1 : "•"}</span>${escapeHtml(b.name)}</button>`,
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

// Star every frame from the current hero up to (and including) the clicked frame, in filmstrip order.
async function rangeStar(targetId) {
  const list = displayFrames.length ? displayFrames : frames;
  let a = list.findIndex((f) => f.id === heroId);
  let b = list.findIndex((f) => f.id === targetId);
  if (a < 0 || b < 0) return;
  if (a > b) [a, b] = [b, a];
  const slice = list.slice(a, b + 1);
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
    // fall back to individual stars
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
  slice.forEach((f) => {
    f.is_print = true;
  });
  toast(`Starred ${ids.length} frame${ids.length > 1 ? "s" : ""}`);
  render();
}

// Star the burst's recommended group auto-pick.
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

async function step(d) {
  pos = (pos + d + series.length) % series.length;
  await load();
}
function moveHero(d) {
  const list = displayFrames.length ? displayFrames : frames;
  if (!list.length) return;
  let i = list.findIndex((f) => f.id === heroId);
  i = (i + d + list.length) % list.length;
  heroId = list[i].id;
  render();
  const el = document.querySelector(`#rv-strip .frame-thumb[data-id="${heroId}"]`);
  if (el) el.scrollIntoView({ block: "nearest", inline: "center" });
}
async function star() {
  const h = hero();
  if (!h) return;
  const r = await post(`/api/p/${slug}/star/${h.id}`, {});
  h.is_print = r.starred;
  toast(r.starred ? "Added to print list" : "Removed from print list");
  render();
}
async function setCriterion(t) {
  const h = hero();
  if (!h) return;
  await post(`/api/p/${slug}/series/${series[pos].id}/pick`, { pick_type: t, image_id: h.id });
  picks[t] = { image_id: h.id, source: "manual" };
  toast(`${META[t].label} → this frame`);
  render();
}

function toggleFullscreen() {
  const el = document.getElementById("view-review");
  if (!document.fullscreenElement) (el.requestFullscreen || el.webkitRequestFullscreen).call(el);
  else document.exitFullscreen();
}

function onKey(e) {
  if (!document.getElementById("lightbox").classList.contains("hidden")) return;
  if (document.querySelector(".modal:not(.hidden)")) return;
  const k = e.key;
  if (k === "ArrowLeft") {
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
  else if (k === " " || k === "Spacebar" || k === "s" || k === "S") {
    e.preventDefault();
    star();
  } else if (k >= "1" && k <= "9") {
    e.preventDefault();
    toggleBucketForHero(+k - 1);
  } else if (k === "g" || k === "G") setCriterion("group");
  else if (k === "c" || k === "C") setCriterion("candid");
  else if (k === "a" || k === "A") setCriterion("aesthetic");
  else if (k === "Enter") {
    const h = hero();
    if (h) openLightbox([{ src: `/api/p/${slug}/image/${h.id}` }]);
  }
}
