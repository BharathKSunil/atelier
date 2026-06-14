// Review / cull: step through bursts, see the recommended frame, star keepers.
import { api, post, pct, toast } from "./api.js";
import { openLightbox } from "./faces.js";

const META = {
  group: { label: "Everyone", desc: "Everyone looking good — eyes open, sharp." },
  candid: { label: "Candid", desc: "Natural, un-posed — a real moment." },
  aesthetic: { label: "Striking", desc: "Most visually striking frame." },
};
const ORDER = ["group", "candid", "aesthetic"];

let slug = null;
let series = [];        // [{id, frame_count}]
let pos = 0;
let frames = [];        // current burst frames (server order, by print_score)
let displayFrames = []; // filmstrip order (featured first) — what nav follows
let picks = {};         // pick_type -> {image_id, source}
let heroId = null;
let keyHandler = null;

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
  if (!keyHandler) {
    keyHandler = onKey;
    window.addEventListener("keydown", keyHandler);
  }
  document.getElementById("rv-prev").onclick = () => step(-1);
  document.getElementById("rv-next").onclick = () => step(1);
  document.getElementById("rv-star").onclick = star;
  document.getElementById("rv-fs").onclick = toggleFullscreen;

  if (!series.length) {
    document.getElementById("rv-stage").innerHTML =
      `<div class="empty-stage">No multi-frame bursts to review.</div>`;
    document.getElementById("rv-rail").innerHTML = "";
    document.getElementById("rv-strip").innerHTML = "";
    document.getElementById("rv-count").textContent = "—";
    return;
  }
  pos = Math.min(pos, series.length - 1);
  await load();
}

export function unmountReview() {
  if (keyHandler) { window.removeEventListener("keydown", keyHandler); keyHandler = null; }
}

async function load() {
  const sid = series[pos].id;
  [frames, picks] = await Promise.all([
    api(`/api/p/${slug}/series/${sid}/images`),
    api(`/api/p/${slug}/series/${sid}/picks`).then((d) => {
      const m = {};
      (d.picks || []).forEach((p) => { m[p.pick_type] = { image_id: p.image_id, source: p.source }; });
      return m;
    }),
  ]);
  heroId = (picks.group && picks.group.image_id) || (frames[0] && frames[0].id);
  render();
}

function hero() { return frames.find((f) => f.id === heroId) || frames[0]; }

function render() {
  const h = hero();
  document.getElementById("rv-count").textContent =
    `Burst ${pos + 1} of ${series.length} · ${frames.length} frames`;
  document.getElementById("rv-progress").style.width = `${((pos + 1) / series.length) * 100}%`;

  // stage
  document.getElementById("rv-stage").innerHTML = h
    ? `${h.is_print ? `<span class="starred-tag">★ In print list</span>` : ""}
       <img src="/api/p/${slug}/image/${h.id}" alt="">`
    : `<div class="empty-stage">—</div>`;
  document.getElementById("rv-stage").onclick = () => {
    const seq = displayFrames.length ? displayFrames : frames;
    if (h) openLightbox(
      seq.map((f) => ({ src: `/api/p/${slug}/image/${f.id}`, cap: `print ${pct(f.print_score)}` })),
      seq.findIndex((f) => f.id === h.id));
  };

  // star button label
  const starBtn = document.getElementById("rv-star");
  starBtn.innerHTML = h && h.is_print ? "★ In print list" : "☆ Add to print list";
  starBtn.classList.toggle("accent", !!(h && h.is_print));

  // filmstrip — criteria + print tags on each frame; suggested/picked/starred sort first
  const byImg = {};
  ORDER.forEach((t) => { const p = picks[t]; if (p) (byImg[p.image_id] = byImg[p.image_id] || []).push({ t, source: p.source }); });
  const featured = (f) => byImg[f.id] || f.is_print;
  displayFrames = [...frames.filter(featured), ...frames.filter((f) => !featured(f))];

  document.getElementById("rv-strip").innerHTML = displayFrames.map((f) => {
    const chips = (byImg[f.id] || [])
      .map((p) => `<span class="ftag crit ${p.source}">${META[p.t].label}</span>`).join("")
      + (f.is_print ? `<span class="ftag print">★ Print</span>` : "");
    return `<div class="frame-thumb ${f.id === heroId ? "cur" : ""} ${f.is_print ? "star" : ""}" data-id="${f.id}">
      <img loading="lazy" src="/api/p/${slug}/image_thumb/${f.id}" alt="">
      <div class="tags">${chips}</div></div>`;
  }).join("");
  document.querySelectorAll("#rv-strip .frame-thumb").forEach((el) => {
    el.onclick = () => { heroId = +el.dataset.id; render(); el.scrollIntoView({ block: "nearest", inline: "center" }); };
  });
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
  if (k === "ArrowLeft") { e.preventDefault(); step(-1); }
  else if (k === "ArrowRight") { e.preventDefault(); step(1); }
  else if (k === "ArrowUp") { e.preventDefault(); moveHero(-1); }
  else if (k === "ArrowDown") { e.preventDefault(); moveHero(1); }
  else if (k === "f" || k === "F") toggleFullscreen();
  else if (k === " " || k === "Spacebar" || k === "s" || k === "S") { e.preventDefault(); star(); }
  else if (k === "1") setCriterion("group");
  else if (k === "2") setCriterion("candid");
  else if (k === "3") setCriterion("aesthetic");
  else if (k === "Enter") { const h = hero(); if (h) openLightbox([{ src: `/api/p/${slug}/image/${h.id}` }]); }
}
