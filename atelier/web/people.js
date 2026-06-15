// People: gallery grid -> person detail with rename / merge / split.
import { api, post, pct, escapeHtml, toast } from "./api.js";
import { openFaceModal } from "./faces.js";
import { confirmDialog, promptDialog } from "./dialog.js";
import { chooseBucket } from "./buckets.js";

let slug = null;
let observers = [];
let selected = new Set();
let gridSel = new Set(); // people ticked on the grid for combined export
let currentPerson = null;
let query = "";
let searchTimer = null;

function killObs() {
  observers.forEach((o) => o.disconnect());
  observers = [];
}

function infinite({ root, sentinel, fetchPage, renderItem, onPage }) {
  let offset = 0,
    busy = false,
    done = false;
  async function more() {
    if (busy || done) return;
    busy = true;
    let r;
    try {
      r = await fetchPage(offset);
    } catch {
      busy = false;
      toast("Could not load list", true);
      return;
    }
    if (onPage) onPage(r, offset);
    (r.items || []).forEach(renderItem);
    if (r.next_offset == null) {
      done = true;
      sentinel.remove();
    } else offset = r.next_offset;
    busy = false;
  }
  const io = new IntersectionObserver(
    (es) => {
      if (es[0].isIntersecting) more();
    },
    { root: root || null, rootMargin: "600px" },
  );
  io.observe(sentinel);
  observers.push(io);
  more();
}

export function mountPeople(s) {
  slug = s;
  query = "";
  gridSel = new Set();
  currentPerson = null; // leaving detail view — stale snapshot must not outlive it
  renderPeople();
}

function renderPeople() {
  killObs();
  const root = document.getElementById("people-root");
  root.innerHTML = `<div class="page-head"><div><div class="eyebrow">Faces grouped by person</div><h1>People</h1></div>
      <div class="spacer"></div>
      <input class="people-search" id="ppl-search" type="search" placeholder="Search people…" spellcheck="false" aria-label="Search people by name" value="${escapeHtml(query)}"></div>
    <p class="muted" style="margin:-12px 0 18px">Tick people to export everyone's photos into one folder to zip and share.</p>
    <div class="people-grid" id="people-list"></div><div class="sentinel" id="ppl-sentinel"></div>
    <div class="select-bar hidden" id="ppl-bar">
      <span id="ppl-bar-n">0 selected</span>
      <button class="btn ghost" id="ppl-bar-clear">Clear</button>
      <button class="btn ghost" id="ppl-bar-bucket">Add to bucket…</button>
      <button class="btn" id="ppl-bar-export">Export photos…</button>
    </div>`;

  const searchEl = document.getElementById("ppl-search");
  searchEl.oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const v = searchEl.value.trim();
      if (v === query) return;
      query = v;
      loadGrid(); // reset paging for the new query
    }, 200);
  };
  document.getElementById("ppl-bar-export").onclick = exportSelectedPeople;
  document.getElementById("ppl-bar-bucket").onclick = addSelectedToBucket;
  document.getElementById("ppl-bar-clear").onclick = () => {
    gridSel.clear();
    loadGrid();
    updateExportBar();
  };
  loadGrid();
}

async function addSelectedToBucket() {
  if (!gridSel.size) return;
  const bid = await chooseBucket(slug);
  if (bid == null) return;
  try {
    const r = await post(`/api/p/${slug}/buckets/${bid}/add-people`, { person_ids: [...gridSel] });
    const np = gridSel.size;
    toast(
      `Added ${r.added} photo${r.added === 1 ? "" : "s"} from ${np} ${np === 1 ? "person" : "people"} to the bucket`,
    );
  } catch {
    toast("Could not add to bucket", true);
  }
}

function updateExportBar() {
  const bar = document.getElementById("ppl-bar");
  if (!bar) return;
  const n = gridSel.size;
  bar.classList.toggle("hidden", n === 0);
  const lbl = document.getElementById("ppl-bar-n");
  if (lbl) lbl.textContent = `${n} ${n === 1 ? "person" : "people"} selected`;
}

async function exportSelectedPeople() {
  if (!gridSel.size) return;
  let r;
  try {
    r = await post("/api/fs/choose", {});
  } catch {
    return;
  }
  if (!r || !r.ok || !r.path) {
    if (r && r.unavailable) toast(r.msg, true);
    return; // cancelled
  }
  toast("Copying originals…");
  try {
    const res = await post(`/api/p/${slug}/persons/export`, { ids: [...gridSel], dest: r.path });
    if (!res.ok) return toast(res.msg || "export failed", true);
    toast(`Copied ${res.count} photos from ${gridSel.size} people → ${res.dest}`);
    gridSel.clear();
    loadGrid();
    updateExportBar();
  } catch {
    toast("Export failed", true);
  }
}

function loadGrid() {
  killObs();
  const list = document.getElementById("people-list");
  list.innerHTML = "";
  let sentinel = document.getElementById("ppl-sentinel");
  if (!sentinel) {
    sentinel = document.createElement("div");
    sentinel.className = "sentinel";
    sentinel.id = "ppl-sentinel";
    list.after(sentinel);
  }
  const q = query ? `&q=${encodeURIComponent(query)}` : "";
  infinite({
    root: null,
    sentinel,
    fetchPage: (off) => api(`/api/p/${slug}/persons?offset=${off}&limit=60${q}`),
    renderItem: (p) => {
      const name = p.display_name || `Person ${p.id}`;
      const alt = `${name}, ${p.cnt} photo${p.cnt === 1 ? "" : "s"}`;
      const el = document.createElement("div");
      el.className = "person" + (gridSel.has(p.id) ? " sel" : "");
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", alt);
      el.innerHTML = `<input type="checkbox" class="psel" aria-label="Select ${escapeHtml(name)} for export"${gridSel.has(p.id) ? " checked" : ""}>
        <div class="ring"><img loading="lazy" src="${p.best_face ? `/api/p/${slug}/thumb/${p.best_face}` : ""}" alt="${escapeHtml(alt)}"></div>
        <div class="nm">${escapeHtml(name)}</div><div class="ct">${p.cnt} photos</div>`;
      const open = () => openPerson(p);
      el.onclick = open;
      el.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
          open();
        }
      };
      const chk = el.querySelector(".psel");
      chk.onclick = (e) => {
        e.stopPropagation();
        if (chk.checked) gridSel.add(p.id);
        else gridSel.delete(p.id);
        el.classList.toggle("sel", chk.checked);
        updateExportBar();
      };
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
      <span class="crumb" id="back-people" role="button" tabindex="0">‹ People</span>
      <input class="name" id="rename-input" value="${escapeHtml(name)}">
      <button class="btn ghost" id="rename-btn">Save</button>
      <button class="btn ghost" id="merge-btn">Merge into…</button>
      <button class="btn ghost" id="bucket-btn">Add to bucket…</button>
      <button class="btn ghost" id="export-btn">Export photos…</button>
      <button class="btn danger hidden" id="split-btn">Split out (0)</button>
      <span class="muted" style="margin-left:auto"><span id="person-count">${p.cnt}</span> photos · tick to merge/split · click to inspect</span>
    </div>
    <div class="grid" id="face-grid"></div><div class="sentinel" id="face-sentinel"></div>`;
  document.getElementById("export-btn").onclick = () => exportPerson(p);
  document.getElementById("bucket-btn").onclick = () => addPersonToBucket(p);
  const back = document.getElementById("back-people");
  back.onclick = () => mountPeople(slug);
  back.onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      mountPeople(slug);
    }
  };
  document.getElementById("rename-btn").onclick = async () => {
    try {
      await post(`/api/p/${slug}/persons/${p.id}/rename`, { name: document.getElementById("rename-input").value });
      toast("Renamed");
      mountPeople(slug);
    } catch {
      toast("Could not rename", true);
    }
  };
  document.getElementById("merge-btn").onclick = () => openMerge(p);
  document.getElementById("split-btn").onclick = () => splitSelected(p);
  const grid = document.getElementById("face-grid");
  infinite({
    root: null,
    sentinel: document.getElementById("face-sentinel"),
    fetchPage: (off) => api(`/api/p/${slug}/persons/${p.id}/faces?offset=${off}&limit=100`),
    // header count came from a (possibly stale) grid snapshot; correct it from the
    // authoritative faces total once the first page lands.
    onPage: (r) => {
      const el = document.getElementById("person-count");
      if (el && r.total != null) el.textContent = r.total;
    },
    renderItem: (f) => {
      const qual = `quality ${pct(f.quality_score)}`;
      const alt = `Face, ${qual}${f.is_best ? ", best of person" : ""}`;
      const cell = document.createElement("div");
      cell.className = "cell" + (f.is_best ? " best" : "");
      cell.setAttribute("role", "button");
      cell.setAttribute("tabindex", "0");
      cell.setAttribute("aria-label", alt);
      cell.innerHTML = `<input type="checkbox" class="cell-check" aria-label="Select this face for merge or split">${f.is_best ? `<span class="tag">BEST</span>` : ""}
        <img loading="lazy" src="/api/p/${slug}/thumb/${f.id}" alt="${escapeHtml(alt)}"><div class="q">${qual}</div>`;
      const chk = cell.querySelector(".cell-check");
      const toggleSel = () => {
        chk.checked ? selected.add(f.id) : selected.delete(f.id);
        cell.classList.toggle("sel", chk.checked);
        const b = document.getElementById("split-btn");
        b.textContent = `Split out (${selected.size})`;
        b.classList.toggle("hidden", selected.size === 0);
      };
      chk.onclick = (e) => {
        e.stopPropagation();
        toggleSel();
      };
      const inspect = () => openFaceModal(slug, f.id);
      cell.onclick = inspect;
      cell.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
          inspect();
        }
      };
      grid.appendChild(cell);
    },
  });
}

async function splitSelected(person) {
  if (!selected.size) return;
  const n = selected.size;
  const fallback = `${person.display_name || `Person ${person.id}`} (split)`;
  const name = await promptDialog({
    title: "Split out faces",
    message: `New person from <b>${n}</b> face${n > 1 ? "s" : ""}.`,
    label: "Name the new person",
    value: "",
    placeholder: fallback,
    okLabel: "Split out",
  });
  if (name == null) return; // cancelled
  try {
    await post(`/api/p/${slug}/persons/${person.id}/split`, { face_ids: [...selected], name: name.trim() || fallback });
    toast("Split into a new person");
    mountPeople(slug);
  } catch {
    toast("Could not split", true);
  }
}

async function exportPerson(p) {
  let r;
  try {
    r = await post("/api/fs/choose", {});
  } catch {
    return;
  }
  if (!r || !r.ok || !r.path) return; // cancelled
  toast("Copying originals…");
  try {
    const res = await post(`/api/p/${slug}/persons/${p.id}/export`, { dest: r.path });
    toast(res.ok ? `Copied ${res.count} photos → ${res.dest}` : res.msg || "export failed", !res.ok);
  } catch {
    toast("Export failed", true);
  }
}

async function addPersonToBucket(p) {
  const bid = await chooseBucket(slug);
  if (bid == null) return;
  try {
    const r = await post(`/api/p/${slug}/buckets/${bid}/add-people`, { person_ids: [p.id] });
    toast(`Added ${r.added} photo${r.added === 1 ? "" : "s"} to the bucket`);
  } catch {
    toast("Could not add to bucket", true);
  }
}

// faces.js fires this after a reject/extract; refresh the open person in place.
window.addEventListener("atelier:people-changed", () => {
  if (!currentPerson) return;
  const view = document.getElementById("view-people");
  if (view && view.classList.contains("hidden")) return; // not on the People view
  openPerson(currentPerson); // re-fetch faces; onPage corrects the count
});

async function openMerge(person) {
  document.getElementById("mg-name").textContent = person.display_name || `Person ${person.id}`;
  const search = document.getElementById("mg-search");
  search.value = "";
  document.getElementById("modal-merge").classList.remove("hidden");
  const all = [];
  let off = 0;
  try {
    while (true) {
      const r = await api(`/api/p/${slug}/persons?offset=${off}&limit=200`);
      all.push(...(r.items || []).filter((x) => x.id !== person.id));
      if (r.next_offset == null) break;
      off = r.next_offset;
    }
  } catch {
    toast("Could not load people", true);
  }
  const listEl = document.getElementById("mg-list");
  const draw = (q) => {
    const ql = q.toLowerCase();
    listEl.innerHTML = "";
    all
      .filter((t) => !ql || (t.display_name || `Person ${t.id}`).toLowerCase().includes(ql))
      .forEach((t) => {
        const nm = t.display_name || `Person ${t.id}`;
        const row = document.createElement("div");
        row.className = "merge-row";
        row.setAttribute("role", "button");
        row.setAttribute("tabindex", "0");
        row.setAttribute("aria-label", `Merge into ${nm}, ${t.cnt} photos`);
        row.innerHTML = `<img loading="lazy" src="${t.best_face ? `/api/p/${slug}/thumb/${t.best_face}` : ""}" alt="">
        <span>${escapeHtml(nm)}</span><span class="muted">${t.cnt}</span>`;
        const doMerge = async () => {
          const fromName = person.display_name || `Person ${person.id}`;
          const ok = await confirmDialog({
            title: "Merge people",
            message: `Merge <b>${escapeHtml(String(person.cnt))}</b> face${person.cnt === 1 ? "" : "s"} of <b>${escapeHtml(fromName)}</b> into <b>${escapeHtml(nm)}</b>?<br><span class="muted">This can’t be undone.</span>`,
            okLabel: "Merge",
            danger: true,
          });
          if (!ok) return;
          try {
            await post(`/api/p/${slug}/persons/merge`, { from_id: person.id, into_id: t.id });
            document.getElementById("modal-merge").classList.add("hidden");
            toast(`Merged into ${nm}`);
            mountPeople(slug);
          } catch {
            toast("Could not merge", true);
          }
        };
        row.onclick = doMerge;
        row.onkeydown = (e) => {
          if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
            e.preventDefault();
            doMerge();
          }
        };
        listEl.appendChild(row);
      });
  };
  draw("");
  search.oninput = () => draw(search.value);
}
document
  .getElementById("mg-x")
  .addEventListener("click", () => document.getElementById("modal-merge").classList.add("hidden"));
document.getElementById("modal-merge").addEventListener("click", (e) => {
  if (e.target.id === "modal-merge") document.getElementById("modal-merge").classList.add("hidden");
});
