// Print list: the starred keepers, paginated (a wedding can star thousands), bulk export.
import { api, post, pct, escapeHtml, base, toast } from "./api.js";
import { openLightbox } from "./faces.js";

let slug = null;
let obs = null;

export async function mountPrints(s) {
  slug = s;
  document.getElementById("prints-export").onclick = exportAll;
  await render();
}

function stopObs() {
  if (obs) {
    obs.disconnect();
    obs = null;
  }
}

async function render() {
  stopObs();
  const root = document.getElementById("prints-root");
  root.innerHTML = `<p class="muted">Loading…</p>`;
  let first;
  try {
    first = await api(`/api/p/${slug}/prints?offset=0&limit=60`);
  } catch {
    root.innerHTML = `<div class="empty"><div class="big">Couldn’t load the print list</div>Check the connection and try again.</div>`;
    return;
  }

  const total = first.total || 0;
  document.getElementById("prints-count").textContent = total ? `${total} photo${total > 1 ? "s" : ""} selected` : "";
  document.getElementById("prints-export").classList.toggle("hidden", !total);
  if (!total) {
    root.innerHTML = `<div class="empty"><div class="big">Nothing selected yet</div>
      Star frames in <b>Review</b> to build your print list.</div>`;
    return;
  }

  root.innerHTML = `<div class="prints-grid"></div><div class="sentinel" id="prints-sentinel"></div>`;
  const grid = root.querySelector(".prints-grid");
  const append = (rows) => (rows || []).forEach((im) => grid.appendChild(card(im)));
  append(first.items);

  let next = first.next_offset;
  const sentinel = document.getElementById("prints-sentinel");
  if (next == null) {
    sentinel.remove();
    return;
  }
  let busy = false;
  obs = new IntersectionObserver(
    async (es) => {
      if (!es[0].isIntersecting || busy || next == null) return;
      busy = true;
      try {
        const r = await api(`/api/p/${slug}/prints?offset=${next}&limit=60`);
        append(r.items);
        next = r.next_offset;
        if (next == null) {
          sentinel.remove();
          stopObs();
        }
      } catch {
        toast("Could not load more", true);
      }
      busy = false;
    },
    { rootMargin: "600px" },
  );
  obs.observe(sentinel);
}

function card(im) {
  const score = im.print_score != null ? `, print score ${pct(im.print_score)}` : "";
  const alt = `${base(im.path)}${score}`;
  const el = document.createElement("div");
  el.className = "print-card";
  el.innerHTML = `<img loading="lazy" src="/api/p/${slug}/image_thumb/${im.id}" alt="${escapeHtml(alt)}"
      role="button" tabindex="0" aria-label="Open ${escapeHtml(alt)}">
    <button class="btn ghost unstar" title="Remove from print list" aria-label="Remove ${escapeHtml(base(im.path))} from print list">✕</button>`;
  const img = el.querySelector("img");
  const open = () => openLightbox([{ src: `/api/p/${slug}/image/${im.id}`, cap: base(im.path) }]);
  img.onclick = open;
  img.onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      open();
    }
  };
  el.querySelector(".unstar").onclick = async () => {
    try {
      await post(`/api/p/${slug}/star/${im.id}`, {});
      toast("Removed");
      render();
    } catch {
      toast("Could not remove", true);
    }
  };
  return el;
}

async function exportAll() {
  try {
    const r = await post(`/api/p/${slug}/prints/export`, {});
    toast(r.ok ? `Exported ${r.count} photos → ${r.dest}` : r.msg || "Export failed", !r.ok);
  } catch {
    toast("Export failed", true);
  }
}
