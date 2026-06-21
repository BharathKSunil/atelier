// Projects dashboard with cover mosaics + new-project modal (native folder picker).
import { api, post, del, escapeHtml, toast } from "./api.js";
import { confirmDialog } from "./dialog.js";

let showArchived = false;

// First-run landing: a blank darkroom contact sheet whose four cells ARE the pipeline,
// the last one a lit "keeper". Decorative sheet (aria-hidden) + the two real CTAs.
const FR_STEPS = [
  { t: "Index photos", s: "detect + embed every face", m: "index" },
  { t: "Group people", s: "cluster faces into people", m: "group" },
  { t: "Find bursts", s: "gather frames from one moment", m: "burst" },
  { t: "Score & pick", s: "the best frame — your keeper", m: "keeper", keeper: true },
];
const FR_BRACKETS = `<svg class="fr-brackets" viewBox="0 0 64 64" fill="none" aria-hidden="true">
  <g stroke="#cda35c" stroke-width="2.6" stroke-linecap="round">
    <path d="M10 20 V10 H20"/><path d="M44 10 H54 V20"/><path d="M54 44 V54 H44"/><path d="M20 54 H10 V44"/>
  </g></svg>`;
// a warm "photo" of a person (echoes the app's demo faces) — the same moment, shown
// at each pipeline stage so the contact sheet reads as a real shoot being processed.
const FR_FACE = `<span class="fr-face"></span>`;
function frMotif(m) {
  if (m === "index") return `${FR_FACE}<span class="fr-detect"></span>`;
  if (m === "group") return `<span class="fr-cluster">${FR_FACE.repeat(3)}</span>`;
  if (m === "burst") return `<span class="fr-burst"><i></i><i></i><i>${FR_FACE}</i></span>`;
  return `${FR_FACE}${FR_BRACKETS}<span class="fr-dot"></span>`; // keeper
}

function firstRunHero() {
  const cells = FR_STEPS.map(
    (st, i) => `<figure class="fr-cell${st.keeper ? " keeper" : ""}" style="--d:${260 + i * 90}ms">
      <div class="fr-frame">${frMotif(st.m)}<span class="fr-no">0${i + 1}</span></div>
      <figcaption><b>${escapeHtml(st.t)}</b><span>${escapeHtml(st.s)}</span></figcaption>
    </figure>`,
  ).join("");
  return `<section class="firstrun">
    <div class="fr-copy">
      <div class="eyebrow fr-rise" style="--d:0ms">A blank sheet, ready to develop</div>
      <h1 class="fr-head fr-rise" style="--d:60ms">Twenty thousand frames.<br />One afternoon to the <em>keepers</em>.</h1>
      <p class="fr-sub fr-rise" style="--d:120ms">
        Atelier indexes a folder of photos, learns every face, gathers each burst back into the moment it
        came from, and surfaces the one frame worth keeping — so you cull by saying <em>yes</em>, not by scrolling.
      </p>
      <div class="fr-actions fr-rise" style="--d:180ms">
        <button class="btn fr-primary">+ Develop your first sheet</button>
        <button class="btn ghost fr-import">Import an existing library →</button>
      </div>
      <p class="fr-trust fr-rise" style="--d:240ms">Originals are never touched · everything runs on this machine.</p>
    </div>
    <div class="fr-sheet fr-rise" style="--d:200ms" aria-hidden="true">
      <div class="fr-rail"></div>
      <div class="fr-cells">${cells}</div>
      <div class="fr-rail"></div>
    </div>
  </section>`;
}

export async function renderDashboard() {
  const wrap = document.getElementById("project-cards");
  wrap.innerHTML = `<p class="muted">Loading…</p>`;
  let projects;
  try {
    projects = await api("/api/projects");
  } catch {
    wrap.innerHTML = `<div class="empty"><div class="big">Couldn’t reach the server</div>
      Make sure Atelier is running, then reload.</div>`;
    return;
  }
  wrap.classList.remove("landing"); // card grid by default; the first-run hero opts out
  const archivedCount = projects.filter((p) => p.archived).length;
  const archBtn = document.getElementById("show-archived-btn");
  if (archBtn) {
    archBtn.hidden = archivedCount === 0 && !showArchived;
    archBtn.classList.toggle("on", showArchived);
    archBtn.textContent = showArchived ? "← Active" : `Archived (${archivedCount})`;
  }
  const visible = projects.filter((p) => (showArchived ? p.archived : !p.archived));
  if (!projects.length) {
    wrap.classList.add("landing");
    wrap.innerHTML = firstRunHero();
    const go = (id) => document.getElementById(id).click();
    wrap.querySelector(".fr-primary").onclick = () => go("new-project-btn");
    wrap.querySelector(".fr-import").onclick = () => go("import-project-btn");
    return;
  }
  if (!visible.length) {
    wrap.innerHTML = `<div class="empty"><div class="big">${showArchived ? "No archived projects" : "Everything archived"}</div></div>`;
    return;
  }
  wrap.innerHTML = "";
  visible.forEach((p, i) => {
    const s = p.stats || {};
    const cover = (p.cover || []).length
      ? `<div class="cover">${p.cover
          .slice(0, 3)
          .map(
            (id) =>
              `<img loading="lazy" src="/api/p/${p.slug}/image_thumb/${id}" alt="Photo from ${escapeHtml(p.name)}">`,
          )
          .join("")}</div>`
      : `<div class="cover empty">${p.running ? "indexing…" : "no photos yet"}</div>`;
    const card = document.createElement("div");
    card.className = `proj-card${p.pinned ? " pinned" : ""}`;
    card.style.animationDelay = `${i * 60}ms`;
    card.innerHTML = `
      ${cover}
      <div class="proj-body">
        <h3>${p.pinned ? `<span class="pin-dot" title="Pinned">★</span> ` : ""}${escapeHtml(p.name)}</h3>
        <div class="proj-path" title="${escapeHtml(p.source_folder)}">${escapeHtml(p.source_folder)}</div>
        <div class="proj-stats">
          <div><b>${s.persons || 0}</b>people</div>
          <div><b>${s.series || 0}</b>bursts</div>
          <div><b>${s.images || 0}</b>photos</div>
        </div>
        <div class="proj-foot">
          ${p.running ? `<span class="pill run">● indexing</span>` : `<span class="pill">${s.faces || 0} faces</span>`}
          <span class="spacer"></span>
          <button class="ic pin ${p.pinned ? "on" : ""}" title="${p.pinned ? "Unpin" : "Pin to top"}">★</button>
          <button class="ic export" title="Export portable copy">⤓</button>
          <button class="ic arch" title="${p.archived ? "Unarchive" : "Archive"}">▣</button>
          <button class="del" title="Delete project">Delete</button>
        </div>
      </div>`;
    card.onclick = (e) => {
      if (!e.target.closest("button")) location.hash = `#/p/${p.slug}/review`;
    };
    const flag = async (patch) => {
      try {
        await post(`/api/projects/${p.slug}/flags`, patch);
        renderDashboard();
      } catch {
        toast("Could not update project", true);
      }
    };
    card.querySelector(".pin").onclick = (e) => (e.stopPropagation(), flag({ pinned: !p.pinned }));
    card.querySelector(".arch").onclick = (e) => (e.stopPropagation(), flag({ archived: !p.archived }));
    card.querySelector(".export").onclick = (e) => {
      e.stopPropagation();
      window.location.href = `/api/projects/${p.slug}/export`;
      toast(`Exporting “${p.name}”…`);
    };
    card.querySelector(".del").onclick = async (e) => {
      e.stopPropagation();
      const ok = await confirmDialog({
        title: "Delete project",
        message: `Delete <b>${escapeHtml(p.name)}</b>? Removes its database only — your original photos are untouched.`,
        okLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
      let r;
      try {
        r = await del(`/api/projects/${p.slug}`);
      } catch {
        return toast("Could not delete project", true);
      }
      if (!r.ok) return toast(r.msg || "could not delete", true);
      renderDashboard();
    };
    wrap.appendChild(card);
  });
}

// ---- import a portable project bundle ----
async function importProject(e) {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  toast(`Importing “${file.name}”…`);
  const fd = new FormData();
  fd.append("file", file);
  let j;
  try {
    j = await api("/api/projects/import", { method: "POST", body: fd, timeout: 120000 });
  } catch {
    return toast("Import failed — is it an Atelier export?", true);
  }
  if (!j.ok) return toast(j.msg || "Import failed", true);
  toast(`Imported “${j.project.name}”`);
  renderDashboard();
}

// ---- new project modal ----
const modal = () => document.getElementById("modal-new");

// per-project bucket setup. "Print list" always exists (the default spacebar target);
// the rest are optional starters the user can include + re-point the default.
const NP_SUGGESTED = ["Socials", "Album", "Candids", "Reject"];
let npDefault = "Print list";
function renderNpBuckets() {
  npDefault = "Print list";
  const el = document.getElementById("np-buckets");
  const row = (name, fixed, checked) =>
    `<label class="np-bk">
       <input type="checkbox" class="np-bk-on" data-name="${name}" ${checked ? "checked" : ""} ${fixed ? "checked disabled" : ""}>
       <span class="np-bk-name">${name}</span>
       <button type="button" class="np-bk-def" data-name="${name}" title="Make this the default (spacebar) bucket">★</button>
     </label>`;
  el.innerHTML = row("Print list", true, true) + NP_SUGGESTED.map((n) => row(n, false, n === "Socials")).join("");
  syncNpDefault();
  el.querySelectorAll(".np-bk-def").forEach((b) => {
    b.onclick = () => {
      npDefault = b.dataset.name;
      const chk = el.querySelector(`.np-bk-on[data-name="${b.dataset.name}"]`);
      if (chk) chk.checked = true;
      syncNpDefault();
    };
  });
}
function syncNpDefault() {
  document.querySelectorAll("#np-buckets .np-bk").forEach((l) => {
    l.classList.toggle("is-default", l.querySelector(".np-bk-on").dataset.name === npDefault);
  });
}
function npBucketConfig() {
  return [...document.querySelectorAll("#np-buckets .np-bk-on")]
    .filter((c) => c.checked || c.dataset.name === npDefault)
    .map((c) => ({ name: c.dataset.name, default: c.dataset.name === npDefault }));
}

const openM = () => {
  document.getElementById("np-name").value = "";
  document.getElementById("np-folder").value = "";
  renderNpBuckets();
  modal().classList.remove("hidden");
};
const closeM = () => modal().classList.add("hidden");
document.getElementById("new-project-btn").addEventListener("click", openM);
document.getElementById("show-archived-btn").addEventListener("click", () => {
  showArchived = !showArchived;
  renderDashboard();
});
document.getElementById("import-project-btn").addEventListener("click", () => {
  document.getElementById("import-file").click();
});
document.getElementById("import-file").addEventListener("change", importProject);
document.getElementById("np-cancel").addEventListener("click", closeM);
document.getElementById("np-cancel-x").addEventListener("click", closeM);
modal().addEventListener("click", (e) => {
  if (e.target.id === "modal-new") closeM();
});
document.getElementById("np-choose").addEventListener("click", async () => {
  try {
    const r = await post("/api/fs/choose", {});
    if (r.ok) document.getElementById("np-folder").value = r.path;
    else if (r.unavailable) {
      toast("Folder picker is macOS-only — type or paste the folder path below", true);
      document.getElementById("np-folder").focus();
    } else if (r.msg && r.msg !== "cancelled") toast(r.msg, true);
  } catch {
    toast("Could not open folder picker", true);
  }
});
document.getElementById("np-create").addEventListener("click", async () => {
  const name = document.getElementById("np-name").value.trim();
  const folder = document.getElementById("np-folder").value.trim();
  if (!name || !folder) return toast("Name and folder are both required", true);
  const btn = document.getElementById("np-create");
  btn.disabled = true;
  let r;
  try {
    r = await post("/api/projects", { name, folder, buckets: npBucketConfig() });
  } catch {
    btn.disabled = false;
    return toast("Could not create project", true);
  }
  btn.disabled = false;
  if (!r.ok) return toast(r.msg || "could not create project", true);
  closeM();
  location.hash = `#/p/${r.project.slug}/run`;
});
