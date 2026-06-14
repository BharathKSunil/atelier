// Projects dashboard with cover mosaics + new-project modal (native folder picker).
import { api, post, del, escapeHtml, base, toast } from "./api.js";

export async function renderDashboard() {
  const wrap = document.getElementById("project-cards");
  wrap.innerHTML = `<p class="muted">Loading…</p>`;
  const projects = await api("/api/projects");
  if (!projects.length) {
    wrap.innerHTML = `<div class="empty"><div class="big">No projects yet</div>
      Create one to index a folder of photos.</div>`;
    return;
  }
  wrap.innerHTML = "";
  projects.forEach((p, i) => {
    const s = p.stats || {};
    const cover = (p.cover || []).length
      ? `<div class="cover">${p.cover.slice(0, 5).map((id) =>
          `<img loading="lazy" src="/api/p/${p.slug}/image_thumb/${id}" alt="">`).join("")}</div>`
      : `<div class="cover empty">${p.running ? "indexing…" : "no photos yet"}</div>`;
    const card = document.createElement("div");
    card.className = "proj-card";
    card.style.animationDelay = `${i * 60}ms`;
    card.innerHTML = `
      ${cover}
      <div class="proj-body">
        <h3>${escapeHtml(p.name)}</h3>
        <div class="proj-path" title="${escapeHtml(p.source_folder)}">${escapeHtml(p.source_folder)}</div>
        <div class="proj-stats">
          <div><b>${s.persons || 0}</b>people</div>
          <div><b>${s.series || 0}</b>bursts</div>
          <div><b>${s.images || 0}</b>photos</div>
        </div>
        <div class="proj-foot">
          ${p.running ? `<span class="pill run">● indexing</span>` : `<span class="pill">${s.faces || 0} faces</span>`}
          <button class="del">Delete</button>
        </div>
      </div>`;
    card.onclick = (e) => { if (!e.target.classList.contains("del")) location.hash = `#/p/${p.slug}/review`; };
    card.querySelector(".del").onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete “${p.name}”? Removes its database only — originals untouched.`)) return;
      const r = await del(`/api/projects/${p.slug}`);
      if (!r.ok) return toast(r.msg || "could not delete", true);
      renderDashboard();
    };
    wrap.appendChild(card);
  });
}

// ---- new project modal ----
const modal = () => document.getElementById("modal-new");
const openM = () => { document.getElementById("np-name").value = ""; document.getElementById("np-folder").value = ""; modal().classList.remove("hidden"); };
const closeM = () => modal().classList.add("hidden");
document.getElementById("new-project-btn").addEventListener("click", openM);
document.getElementById("np-cancel").addEventListener("click", closeM);
document.getElementById("np-cancel-x").addEventListener("click", closeM);
modal().addEventListener("click", (e) => { if (e.target.id === "modal-new") closeM(); });
document.getElementById("np-choose").addEventListener("click", async () => {
  const r = await post("/api/fs/choose", {});
  if (r.ok) document.getElementById("np-folder").value = r.path;
  else if (r.msg && r.msg !== "cancelled or unavailable") toast(r.msg, true);
});
document.getElementById("np-create").addEventListener("click", async () => {
  const name = document.getElementById("np-name").value.trim();
  const folder = document.getElementById("np-folder").value.trim();
  if (!name || !folder) return toast("Name and folder are both required", true);
  const btn = document.getElementById("np-create");
  btn.disabled = true;
  const r = await post("/api/projects", { name, folder });
  btn.disabled = false;
  if (!r.ok) return toast(r.msg || "could not create project", true);
  closeM();
  location.hash = `#/p/${r.project.slug}/run`;
});
