// Print list: the starred keepers, with bulk export.
import { api, post, pct, escapeHtml, base, toast } from "./api.js";
import { openLightbox } from "./faces.js";

let slug = null;

export async function mountPrints(s) {
  slug = s;
  document.getElementById("prints-export").onclick = exportAll;
  await render();
}

async function render() {
  const root = document.getElementById("prints-root");
  root.innerHTML = `<p class="muted">Loading…</p>`;
  let rows;
  try { rows = await api(`/api/p/${slug}/prints`); }
  catch { root.innerHTML = `<div class="empty"><div class="big">Couldn’t load the print list</div>Check the connection and try again.</div>`; return; }
  document.getElementById("prints-count").textContent = rows.length
    ? `${rows.length} photo${rows.length > 1 ? "s" : ""} selected`
    : "";
  document.getElementById("prints-export").classList.toggle("hidden", !rows.length);
  if (!rows.length) {
    root.innerHTML = `<div class="empty"><div class="big">Nothing selected yet</div>
      Star frames in <b>Review</b> to build your print list.</div>`;
    return;
  }
  root.innerHTML = `<div class="prints-grid"></div>`;
  const grid = root.querySelector(".prints-grid");
  rows.forEach((im) => {
    const score = im.print_score != null ? `, print score ${pct(im.print_score)}` : "";
    const alt = `${base(im.path)}${score}`;
    const card = document.createElement("div");
    card.className = "print-card";
    card.innerHTML = `<img loading="lazy" src="/api/p/${slug}/image_thumb/${im.id}" alt="${escapeHtml(alt)}"
        role="button" tabindex="0" aria-label="Open ${escapeHtml(alt)}">
      <button class="btn ghost unstar" title="Remove from print list" aria-label="Remove ${escapeHtml(base(im.path))} from print list">✕</button>`;
    const img = card.querySelector("img");
    const open = () => openLightbox([{ src: `/api/p/${slug}/image/${im.id}`, cap: base(im.path) }]);
    img.onclick = open;
    img.onkeydown = (e) => { if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") { e.preventDefault(); open(); } };
    card.querySelector(".unstar").onclick = async () => {
      try { await post(`/api/p/${slug}/star/${im.id}`, {}); toast("Removed"); render(); }
      catch { toast("Could not remove", true); }
    };
    grid.appendChild(card);
  });
}

async function exportAll() {
  try {
    const r = await post(`/api/p/${slug}/prints/export`, {});
    toast(r.ok ? `Exported ${r.count} photos → ${r.dest}` : "Export failed", !r.ok);
  } catch { toast("Export failed", true); }
}
