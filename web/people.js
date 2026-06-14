// People: gallery grid -> person detail with rename / merge / split.
import { api, post, pct, escapeHtml, toast } from "./api.js";
import { openFaceModal } from "./faces.js";

let slug = null;
let observers = [];
let selected = new Set();
let currentPerson = null;

function killObs() { observers.forEach((o) => o.disconnect()); observers = []; }

function infinite({ root, sentinel, fetchPage, renderItem }) {
  let offset = 0, busy = false, done = false;
  async function more() {
    if (busy || done) return;
    busy = true;
    const r = await fetchPage(offset);
    (r.items || []).forEach(renderItem);
    if (r.next_offset == null) { done = true; sentinel.remove(); } else offset = r.next_offset;
    busy = false;
  }
  const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) more(); }, { root: root || null, rootMargin: "600px" });
  io.observe(sentinel);
  observers.push(io);
  more();
}

export function mountPeople(s) {
  slug = s;
  killObs();
  const root = document.getElementById("people-root");
  root.innerHTML = `<div class="page-head"><div><div class="eyebrow">Faces grouped by person</div><h1>People</h1></div></div>
    <div class="people-grid" id="people-list"></div><div class="sentinel" id="ppl-sentinel"></div>`;
  const list = document.getElementById("people-list");
  infinite({
    root: null, sentinel: document.getElementById("ppl-sentinel"),
    fetchPage: (off) => api(`/api/p/${slug}/persons?offset=${off}&limit=60`),
    renderItem: (p) => {
      const name = p.display_name || `Person ${p.id}`;
      const el = document.createElement("div");
      el.className = "person";
      el.innerHTML = `<div class="ring"><img loading="lazy" src="${p.best_face ? `/api/p/${slug}/thumb/${p.best_face}` : ""}" alt=""></div>
        <div class="nm">${escapeHtml(name)}</div><div class="ct">${p.cnt} photos</div>`;
      el.onclick = () => openPerson(p);
      list.appendChild(el);
    },
  });
}

function openPerson(p) {
  killObs();
  currentPerson = p;
  selected = new Set();
  const name = p.display_name || `Person ${p.id}`;
  const root = document.getElementById("people-root");
  root.innerHTML = `
    <div class="detail-head">
      <span class="crumb" id="back-people">‹ People</span>
      <input class="name" id="rename-input" value="${escapeHtml(name)}">
      <button class="btn ghost" id="rename-btn">Save</button>
      <button class="btn ghost" id="merge-btn">Merge into…</button>
      <button class="btn danger hidden" id="split-btn">Split out (0)</button>
      <span class="muted" style="margin-left:auto">${p.cnt} photos · tick to merge/split · click to inspect</span>
    </div>
    <div class="grid" id="face-grid"></div><div class="sentinel" id="face-sentinel"></div>`;
  document.getElementById("back-people").onclick = () => mountPeople(slug);
  document.getElementById("rename-btn").onclick = async () => {
    await post(`/api/p/${slug}/persons/${p.id}/rename`, { name: document.getElementById("rename-input").value });
    toast("Renamed"); mountPeople(slug);
  };
  document.getElementById("merge-btn").onclick = () => openMerge(p);
  document.getElementById("split-btn").onclick = async () => {
    if (!selected.size) return;
    await post(`/api/p/${slug}/persons/${p.id}/split`, { face_ids: [...selected] });
    toast("Split into a new person"); mountPeople(slug);
  };
  const grid = document.getElementById("face-grid");
  infinite({
    root: null, sentinel: document.getElementById("face-sentinel"),
    fetchPage: (off) => api(`/api/p/${slug}/persons/${p.id}/faces?offset=${off}&limit=100`),
    renderItem: (f) => {
      const cell = document.createElement("div");
      cell.className = "cell" + (f.is_best ? " best" : "");
      cell.innerHTML = `<input type="checkbox" class="cell-check">${f.is_best ? `<span class="tag">BEST</span>` : ""}
        <img loading="lazy" src="/api/p/${slug}/thumb/${f.id}" alt=""><div class="q">quality ${pct(f.quality_score)}</div>`;
      const chk = cell.querySelector(".cell-check");
      chk.onclick = (e) => {
        e.stopPropagation();
        chk.checked ? selected.add(f.id) : selected.delete(f.id);
        cell.classList.toggle("sel", chk.checked);
        const b = document.getElementById("split-btn");
        b.textContent = `Split out (${selected.size})`;
        b.classList.toggle("hidden", selected.size === 0);
      };
      cell.onclick = () => openFaceModal(slug, f.id);
      grid.appendChild(cell);
    },
  });
}

async function openMerge(person) {
  document.getElementById("mg-name").textContent = person.display_name || `Person ${person.id}`;
  const search = document.getElementById("mg-search");
  search.value = "";
  document.getElementById("modal-merge").classList.remove("hidden");
  const all = [];
  let off = 0;
  while (true) {
    const r = await api(`/api/p/${slug}/persons?offset=${off}&limit=200`);
    all.push(...(r.items || []).filter((x) => x.id !== person.id));
    if (r.next_offset == null) break;
    off = r.next_offset;
  }
  const listEl = document.getElementById("mg-list");
  const draw = (q) => {
    const ql = q.toLowerCase();
    listEl.innerHTML = "";
    all.filter((t) => !ql || (t.display_name || `Person ${t.id}`).toLowerCase().includes(ql)).forEach((t) => {
      const nm = t.display_name || `Person ${t.id}`;
      const row = document.createElement("div");
      row.className = "merge-row";
      row.innerHTML = `<img loading="lazy" src="${t.best_face ? `/api/p/${slug}/thumb/${t.best_face}` : ""}" alt="">
        <span>${escapeHtml(nm)}</span><span class="muted">${t.cnt}</span>`;
      row.onclick = async () => {
        await post(`/api/p/${slug}/persons/merge`, { from_id: person.id, into_id: t.id });
        document.getElementById("modal-merge").classList.add("hidden");
        toast(`Merged into ${nm}`); mountPeople(slug);
      };
      listEl.appendChild(row);
    });
  };
  draw("");
  search.oninput = () => draw(search.value);
}
document.getElementById("mg-x").addEventListener("click", () => document.getElementById("modal-merge").classList.add("hidden"));
document.getElementById("modal-merge").addEventListener("click", (e) => {
  if (e.target.id === "modal-merge") document.getElementById("modal-merge").classList.add("hidden");
});
