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
  const rows = await api(`/api/p/${slug}/prints`);
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
    const card = document.createElement("div");
    card.className = "print-card";
    card.innerHTML = `<img loading="lazy" src="/api/p/${slug}/image_thumb/${im.id}" alt="">
      <button class="btn ghost unstar" title="Remove">✕</button>`;
    card.querySelector("img").onclick = () =>
      openLightbox([{ src: `/api/p/${slug}/image/${im.id}`, cap: base(im.path) }]);
    card.querySelector(".unstar").onclick = async () => {
      await post(`/api/p/${slug}/star/${im.id}`, {});
      toast("Removed"); render();
    };
    grid.appendChild(card);
  });
}

async function exportAll() {
  const r = await post(`/api/p/${slug}/prints/export`, {});
  toast(r.ok ? `Exported ${r.count} photos → ${r.dest}` : "Export failed", !r.ok);
}
