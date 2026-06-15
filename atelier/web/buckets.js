// Buckets: user-defined collections (a photo can be in many). Manage + browse + export.
import { api, post, del, escapeHtml, base, toast } from "./api.js";
import { openLightbox } from "./faces.js";
import { confirmDialog, promptDialog } from "./dialog.js";

let slug = null;
let buckets = [];
let active = null; // selected bucket id
let obs = null;

export async function mountBuckets(s) {
  slug = s;
  active = null;
  await refresh();
}

export function unmountBuckets() {
  stopObs();
}

function stopObs() {
  if (obs) {
    obs.disconnect();
    obs = null;
  }
}

async function refresh() {
  try {
    buckets = await api(`/api/p/${slug}/buckets`);
  } catch {
    buckets = [];
  }
  if ((active == null || !buckets.some((b) => b.id === active)) && buckets.length) active = buckets[0].id;
  render();
}

function render() {
  stopObs();
  const root = document.getElementById("buckets-root");
  const tabs = buckets
    .map(
      (b, i) =>
        `<button class="bucket-tab ${b.id === active ? "on" : ""}" data-id="${b.id}">
           <span class="dot" style="background:${escapeHtml(b.color || "#cda35c")}"></span>
           <span class="k">${i < 9 ? i + 1 : "•"}</span>${escapeHtml(b.name)}<em>${b.count}</em></button>`,
    )
    .join("");
  root.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Your collections</div><h1>Buckets</h1></div>
      <div class="spacer"></div><button class="btn" id="bk-new">+ New bucket</button></div>
    <p class="muted" style="max-width:700px;margin-bottom:18px">Group photos into named buckets — a photo can live in many.
      In <b>Review</b>, press a bucket's number to drop the current frame into it. Export a bucket to zip and share.</p>
    <div class="bucket-tabs">${tabs || `<span class="muted">No buckets yet — create your first one.</span>`}</div>
    <div id="bucket-detail"></div>`;
  document.getElementById("bk-new").onclick = newBucket;
  root.querySelectorAll(".bucket-tab").forEach((el) => {
    el.onclick = () => {
      active = +el.dataset.id;
      render();
    };
  });
  renderDetail();
}

async function newBucket() {
  const raw = await promptDialog({
    title: "New bucket",
    label: "Bucket name",
    placeholder: "e.g. Social media, Candids, For keeps, Private",
    okLabel: "Create",
  });
  const name = (raw || "").trim();
  if (!name) return;
  try {
    const r = await post(`/api/p/${slug}/buckets`, { name });
    active = r.id;
    toast(`Created “${name}”`);
    await refresh();
  } catch {
    toast("Could not create bucket", true);
  }
}

function renderDetail() {
  const wrap = document.getElementById("bucket-detail");
  if (!wrap) return;
  const b = buckets.find((x) => x.id === active);
  if (!b) {
    wrap.innerHTML = "";
    return;
  }
  wrap.innerHTML = `
    <div class="bucket-bar">
      <input class="bucket-name" id="bk-name" value="${escapeHtml(b.name)}" aria-label="Bucket name">
      <input type="color" id="bk-color" value="${escapeHtml(b.color || "#cda35c")}" aria-label="Bucket colour" title="Bucket colour">
      <button class="btn ghost" id="bk-save">Save</button>
      <div class="spacer"></div>
      <span class="muted">${b.count} photo${b.count === 1 ? "" : "s"}</span>
      <button class="btn" id="bk-export"${b.count ? "" : " disabled"}>Export…</button>
      <button class="btn danger" id="bk-del">Delete</button>
    </div>
    <div class="prints-grid" id="bk-grid"></div><div class="sentinel" id="bk-sentinel"></div>`;
  document.getElementById("bk-save").onclick = () => saveBucket(b.id);
  document.getElementById("bk-del").onclick = () => deleteBucket(b);
  document.getElementById("bk-export").onclick = () => exportBucket(b);
  loadImages(b.id);
}

async function saveBucket(id) {
  const name = document.getElementById("bk-name").value.trim();
  const color = document.getElementById("bk-color").value;
  if (!name) return toast("Name is required", true);
  try {
    await api(`/api/p/${slug}/buckets/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, color }),
    });
    toast("Saved");
    await refresh();
  } catch {
    toast("Could not save", true);
  }
}

async function deleteBucket(b) {
  const ok = await confirmDialog({
    title: "Delete bucket",
    message: `Delete <b>${escapeHtml(b.name)}</b>? Your photos stay in the library — only this bucket is removed.`,
    okLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await del(`/api/p/${slug}/buckets/${b.id}`);
    toast("Bucket deleted");
    active = null;
    await refresh();
  } catch {
    toast("Could not delete", true);
  }
}

async function exportBucket(b) {
  let r;
  try {
    r = await post("/api/fs/choose", {});
  } catch {
    return;
  }
  if (!r || !r.ok || !r.path) {
    if (r && r.unavailable) toast(r.msg, true);
    return;
  }
  toast("Copying originals…");
  try {
    const res = await post(`/api/p/${slug}/buckets/${b.id}/export`, { dest: r.path });
    toast(res.ok ? `Exported ${res.count} photos → ${res.dest}` : res.msg || "export failed", !res.ok);
  } catch {
    toast("Export failed", true);
  }
}

function loadImages(bid) {
  stopObs();
  const grid = document.getElementById("bk-grid");
  const sentinel = document.getElementById("bk-sentinel");
  if (!grid || !sentinel) return;
  let next = 0,
    busy = false,
    done = false;
  const more = async () => {
    if (busy || done) return;
    busy = true;
    let r;
    try {
      r = await api(`/api/p/${slug}/buckets/${bid}/images?offset=${next}&limit=60`);
    } catch {
      busy = false;
      return;
    }
    (r.items || []).forEach((im) => grid.appendChild(card(bid, im)));
    if (r.next_offset == null) {
      done = true;
      sentinel.remove();
      stopObs();
    } else next = r.next_offset;
    busy = false;
  };
  obs = new IntersectionObserver(
    (es) => {
      if (es[0].isIntersecting) more();
    },
    { rootMargin: "600px" },
  );
  obs.observe(sentinel);
  more();
}

function card(bid, im) {
  const alt = base(im.path);
  const el = document.createElement("div");
  el.className = "print-card";
  el.innerHTML = `<img loading="lazy" src="/api/p/${slug}/image_thumb/${im.id}" alt="${escapeHtml(alt)}"
      role="button" tabindex="0" aria-label="Open ${escapeHtml(alt)}">
    <button class="btn ghost unstar" title="Remove from bucket" aria-label="Remove ${escapeHtml(alt)} from bucket">✕</button>`;
  const img = el.querySelector("img");
  const open = () => openLightbox([{ src: `/api/p/${slug}/image/${im.id}`, cap: alt }]);
  img.onclick = open;
  img.onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      open();
    }
  };
  el.querySelector(".unstar").onclick = async () => {
    try {
      await post(`/api/p/${slug}/buckets/${bid}/toggle`, { image_id: im.id });
      el.remove();
      const b = buckets.find((x) => x.id === bid);
      if (b) b.count = Math.max(0, b.count - 1);
      toast("Removed from bucket");
    } catch {
      toast("Could not remove", true);
    }
  };
  return el;
}
