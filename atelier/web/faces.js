// Keyboard-driven lightbox (gallery) + face detail modal.
import { api, post, pct, escapeHtml, base, toast } from "./api.js";

let items = [], idx = 0;

export function openLightbox(arg, start = 0) {
  items = Array.isArray(arg) ? arg : [{ src: arg }];
  idx = start;
  show();
}
function show() {
  const it = items[idx];
  if (!it) return;
  document.getElementById("lightbox-img").src = it.src;
  document.getElementById("lb-cap").textContent = it.cap || "";
  const multi = items.length > 1;
  document.getElementById("lb-prev").style.display = multi ? "" : "none";
  document.getElementById("lb-next").style.display = multi ? "" : "none";
  document.getElementById("lightbox").classList.remove("hidden");
}
function move(d) { idx = (idx + d + items.length) % items.length; show(); }
function close() { document.getElementById("lightbox").classList.add("hidden"); }

document.getElementById("lb-close").onclick = close;
document.getElementById("lb-prev").onclick = () => move(-1);
document.getElementById("lb-next").onclick = () => move(1);
document.getElementById("lightbox").addEventListener("click", (e) => { if (e.target.id === "lightbox") close(); });
window.addEventListener("keydown", (e) => {
  if (document.getElementById("lightbox").classList.contains("hidden")) return;
  if (e.key === "Escape") close();
  else if (e.key === "ArrowLeft") move(-1);
  else if (e.key === "ArrowRight") move(1);
});

// ---- face detail modal ----
function bar(label, v) {
  return `<div class="qbar"><span>${label}</span>
    <div class="qbar-track"><div class="qbar-fill" style="width:${Math.round((v || 0) * 100)}%"></div></div>
    <em>${pct(v)}</em></div>`;
}
export async function openFaceModal(slug, fid) {
  const box = document.getElementById("face-box");
  box.innerHTML = `<p class="muted">Loading…</p>`;
  document.getElementById("modal-face").classList.remove("hidden");
  let f;
  try { f = await api(`/api/p/${slug}/face/${fid}`); }
  catch {
    box.innerHTML = `<button class="modal-x" id="face-x" aria-label="Close">&times;</button><p class="muted">Could not load this face.</p>`;
    box.querySelector("#face-x").onclick = () => document.getElementById("modal-face").classList.add("hidden");
    return;
  }
  const name = f.display_name || (f.person_id >= 0 ? `Person ${f.person_id}` : "Ungrouped");
  box.innerHTML = `
    <button class="modal-x" id="face-x" aria-label="Close">&times;</button>
    <div class="face-detail">
      <img class="face-crop" src="/api/p/${slug}/thumb/${f.id}" alt="${escapeHtml(name)}, quality ${pct(f.quality_score)}">
      <div class="face-meta">
        <div class="eyebrow">Face</div><h3>${escapeHtml(name)}</h3>
        <div class="kv"><span>Detection confidence</span><b>${pct(f.confidence)}</b></div>
        <div class="kv"><span>Overall quality</span><b>${pct(f.quality_score)}</b></div>
        <div style="margin:14px 0">
          ${bar("Sharpness", f.face_sharpness)}${bar("Eyes open", f.eye_open)}
          ${bar("Smile", f.smile)}${bar("Frontality", f.frontality)}
        </div>
        <div class="src-name">${escapeHtml(base(f.path))}</div>
        <div class="src-path">${escapeHtml(f.path)}</div>
        <div class="face-actions">
          <button class="btn" id="face-open">Open original</button>
          <button class="btn ghost" id="face-reveal">Reveal in Finder</button>
        </div>
      </div>
    </div>`;
  const closeM = () => document.getElementById("modal-face").classList.add("hidden");
  box.querySelector("#face-x").onclick = closeM;
  box.querySelector("#face-open").onclick = () =>
    openLightbox([{ src: `/api/p/${slug}/image/${f.image_id}`, cap: base(f.path) }]);
  box.querySelector("#face-reveal").onclick = async () => {
    try {
      const r = await post("/api/fs/reveal", { path: f.path });
      toast(r.ok ? "Revealed in Finder" : "Could not reveal file", !r.ok);
    } catch { toast("Could not reveal file", true); }
  };
}
document.getElementById("modal-face").addEventListener("click", (e) => {
  if (e.target.id === "modal-face") document.getElementById("modal-face").classList.add("hidden");
});
