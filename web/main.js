// Hash router: #/  ->  dashboard ; #/p/<slug>/<mode> -> project workspace.
import { api } from "./api.js";
import { renderDashboard } from "./dashboard.js";
import { mountReview, unmountReview } from "./cull.js";
import { mountPeople } from "./people.js";
import { mountPrints } from "./prints.js";
import { mountRun, unmountRun } from "./run.js";
import { mountSettings } from "./settings.js";

const MODES = [["review", "Review"], ["people", "People"], ["prints", "Print list"],
  ["run", "Run"], ["settings", "Settings"]];

function parse() {
  const m = location.hash.replace(/^#/, "").match(/^\/p\/([^/]+)\/(\w+)/);
  return m ? { slug: m[1], mode: m[2] } : { slug: null };
}

async function render() {
  const r = parse();
  if (!r.slug) return showDashboard();
  showProject(r.slug, MODES.some(([k]) => k === r.mode) ? r.mode : "review");
}

function showDashboard() {
  unmountReview(); unmountRun();
  document.getElementById("screen-project").classList.add("hidden");
  document.getElementById("screen-dashboard").classList.remove("hidden");
  document.getElementById("crumb").classList.add("hidden");
  document.getElementById("modes").classList.add("hidden");
  renderDashboard();
}

async function showProject(slug, mode) {
  document.getElementById("screen-dashboard").classList.add("hidden");
  document.getElementById("screen-project").classList.remove("hidden");

  const list = await api("/api/projects").catch(() => []);
  const proj = (list || []).find((p) => p.slug === slug);
  const crumb = document.getElementById("crumb");
  crumb.classList.remove("hidden");
  crumb.textContent = proj ? proj.name : slug;

  const modesEl = document.getElementById("modes");
  modesEl.classList.remove("hidden");
  modesEl.innerHTML = MODES.map(([k, label]) =>
    `<button class="mode ${k === mode ? "active" : ""}" data-mode="${k}">${label}</button>`).join("");
  modesEl.querySelectorAll(".mode").forEach((b) => {
    b.onclick = () => { location.hash = `#/p/${slug}/${b.dataset.mode}`; };
  });

  for (const [k] of MODES) document.getElementById(`view-${k}`).classList.toggle("hidden", k !== mode);
  if (mode !== "review") unmountReview();
  if (mode !== "run") unmountRun();

  if (mode === "review") mountReview(slug);
  else if (mode === "people") mountPeople(slug);
  else if (mode === "prints") mountPrints(slug);
  else if (mode === "run") mountRun(slug);
  else if (mode === "settings") mountSettings(slug);
}

document.getElementById("brand").onclick = () => { location.hash = "#/"; };
document.getElementById("crumb").onclick = () => { location.hash = "#/"; };

// one global Escape: close the topmost open overlay (lightbox first, then any modal)
window.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const lb = document.getElementById("lightbox");
  if (!lb.classList.contains("hidden")) { lb.classList.add("hidden"); return; }
  const open = document.querySelector(".modal:not(.hidden)");
  if (open) open.classList.add("hidden");
});

window.addEventListener("hashchange", render);
render();
