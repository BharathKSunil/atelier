// Hash router: #/  ->  dashboard ; #/p/<slug>/<mode> -> project workspace.
import { api } from "./api.js";
import { renderDashboard } from "./dashboard.js";
import { mountReview, unmountReview } from "./cull.js";
import { mountPeople } from "./people.js";
import { mountPrints } from "./prints.js";
import { mountRun, unmountRun } from "./run.js";
import { mountSettings } from "./settings.js";

const MODES = [
  ["review", "Review"],
  ["people", "People"],
  ["prints", "Print list"],
  ["run", "Run"],
  ["settings", "Settings"],
];

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
  unmountReview();
  unmountRun();
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
  modesEl.innerHTML = MODES.map(
    ([k, label]) => `<button class="mode ${k === mode ? "active" : ""}" data-mode="${k}">${label}</button>`,
  ).join("");
  modesEl.querySelectorAll(".mode").forEach((b) => {
    b.onclick = () => {
      location.hash = `#/p/${slug}/${b.dataset.mode}`;
    };
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

document.getElementById("brand").onclick = () => {
  location.hash = "#/";
};
document.getElementById("crumb").onclick = () => {
  location.hash = "#/";
};

// ---- focus trap for modals ----
const FOCUSABLE =
  'a[href],area[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),button:not([disabled]),[tabindex]:not([tabindex="-1"])';

function focusableIn(el) {
  return [...el.querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null || n === document.activeElement);
}

// Trap state per modal id so re-entrancy / multiple modals are safe.
const traps = new Map();

function trapFocus(modal) {
  if (!modal || traps.has(modal)) return;
  const box = modal.querySelector(".modal-box") || modal;
  const prev = document.activeElement;
  const onKeydown = (e) => {
    if (e.key !== "Tab") return;
    const items = focusableIn(box);
    if (!items.length) {
      e.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey) {
      if (active === first || !box.contains(active)) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (active === last || !box.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  modal.addEventListener("keydown", onKeydown);
  traps.set(modal, { prev, onKeydown });
  // focus first focusable element (defer so freshly-injected content is present)
  requestAnimationFrame(() => {
    const items = focusableIn(box);
    (items[0] || box).focus();
  });
}

function releaseFocus(modal) {
  const t = traps.get(modal);
  if (!t) return;
  modal.removeEventListener("keydown", t.onKeydown);
  traps.delete(modal);
  if (t.prev && typeof t.prev.focus === "function" && document.contains(t.prev)) {
    t.prev.focus();
  }
}

// Watch each modal's hidden-class toggling and apply/release the trap automatically,
// so every open/close call site (dashboard, people, faces) is covered without changes.
function watchModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  let wasOpen = !modal.classList.contains("hidden");
  if (wasOpen) trapFocus(modal);
  const mo = new MutationObserver(() => {
    const open = !modal.classList.contains("hidden");
    if (open === wasOpen) return;
    wasOpen = open;
    if (open) trapFocus(modal);
    else releaseFocus(modal);
  });
  mo.observe(modal, { attributes: true, attributeFilter: ["class"] });
}
["modal-new", "modal-merge", "modal-face"].forEach(watchModal);

// one global Escape: close the topmost open overlay (lightbox first, then any modal)
window.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const lb = document.getElementById("lightbox");
  if (!lb.classList.contains("hidden")) {
    lb.classList.add("hidden");
    return;
  }
  const open = document.querySelector(".modal:not(.hidden)");
  if (open) open.classList.add("hidden");
});

window.addEventListener("hashchange", render);
render();
