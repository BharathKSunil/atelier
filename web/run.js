// Live run console: phase steps, progress, streaming log, live face grid.
import { api, post } from "./api.js";

let timer = null;
let slug = null;

export function mountRun(s) {
  slug = s;
  document.getElementById("run-again").onclick = async () => { await post(`/api/p/${slug}/run`, {}); poll(); };
  poll();
}
export function unmountRun() {
  clearTimeout(timer);
  timer = null;
}

async function poll() {
  if (!slug) return;
  const me = slug;
  let s;
  try {
    s = await api(`/api/p/${me}/run/status`);
  } catch {
    if (slug === me) { clearTimeout(timer); timer = setTimeout(poll, 3000); }  // retry, don't freeze
    return;
  }
  if (slug !== me) return;
  render(s);
  clearTimeout(timer);
  if (s.running) timer = setTimeout(poll, 1200);
}

function render(s) {
  const phases = s.all_phases || ["index", "cluster", "series", "score"];
  const done = new Set(s.phases_done || []);
  document.getElementById("run-source").textContent = s.folder ? `Source: ${s.folder}` : "";
  document.getElementById("phase-steps").innerHTML = phases.map((p) => {
    const cls = done.has(p) ? "done" : (s.phase === p ? "active" : "");
    const mk = done.has(p) ? "✓" : (s.phase === p ? "●" : "○");
    return `<div class="step ${cls}"><span>${mk}</span>${p}</div>`;
  }).join('<span class="step-sep">·</span>');

  let w = 0;
  if (s.phase === "index" && s.index_total) w = (s.index_done / s.index_total) * 100;
  else if (!s.running && done.size === phases.length) w = 100;
  else if (s.running) w = 100;
  const fill = document.getElementById("run-bar-fill");
  fill.style.width = Math.round(w) + "%";
  fill.classList.toggle("indeterminate", s.running && s.phase !== "index");

  const status = s.running ? `Running: ${s.phase || "…"}` : s.error ? "Failed" :
    (done.size ? "Complete ✓" : "Idle");
  const parts = [];
  if (s.index_total) parts.push(`${s.index_done}/${s.index_total} images`);
  if (s.faces_found != null) parts.push(`${s.faces_found} faces`);
  if (s.errors) parts.push(`${s.errors} errors`);
  document.getElementById("run-counts").textContent = `${status}   ${parts.join(" · ")}`;

  const err = document.getElementById("run-error");
  if (s.error) { err.textContent = s.error; err.classList.remove("hidden"); } else err.classList.add("hidden");

  const log = document.getElementById("run-log");
  log.textContent = (s.log || []).join("\n");
  log.scrollTop = log.scrollHeight;

  document.getElementById("live-face-count").textContent = s.faces_found || 0;
  document.getElementById("live-face-grid").innerHTML = (s.recent_face_ids || [])
    .map((id) => `<img loading="lazy" src="/api/p/${slug}/thumb/${id}" alt="">`).join("");
  document.getElementById("run-again").classList.toggle("hidden", s.running);
}
