// Per-project tunables. Grouped knobs; each group saves + triggers the right re-run.
import { api, post, escapeHtml, toast } from "./api.js";

const GROUP_ACTION = {
  Detection: { affects: "reindex", label: "Save & re-index (full)", note: "re-detects every photo — slow" },
  Clustering: { affects: "recluster", label: "Save & re-cluster", note: "fast — minutes" },
  Series: { affects: "regroup", label: "Save & re-group bursts", note: "fast — minutes" },
};

let slug = null;
let spec = [];
let values = {};

export async function mountSettings(s) {
  slug = s;
  const data = await api(`/api/p/${slug}/settings`);
  spec = data.spec || [];
  values = data.values || {};
  render();
}

function render() {
  const root = document.getElementById("settings-root");
  const groups = [...new Set(spec.map((k) => k.group))];
  root.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Per-project tuning</div><h1>Settings</h1></div>
      <div class="spacer"></div><button class="btn ghost" id="set-save">Save only</button></div>
    <p class="muted" style="max-width:680px;margin-bottom:24px">Adjust how faces are detected, grouped into people, and how bursts are formed.
      Detection changes need a full re-index; clustering and burst changes re-run in minutes.</p>
    <div class="set-groups">${groups.map(groupCard).join("")}</div>`;

  spec.forEach((k) => {
    const slider = root.querySelector(`input[type=range][data-k="${k.key}"]`);
    const num = root.querySelector(`input[type=number][data-k="${k.key}"]`);
    const sync = (v) => { values[k.key] = +v; slider.value = v; num.value = v; };
    slider.oninput = () => sync(slider.value);
    num.oninput = () => sync(num.value);
  });
  root.querySelector("#set-save").onclick = () => saveOnly();
  groups.forEach((g) => {
    const btn = root.querySelector(`button[data-group="${g}"]`);
    if (btn) btn.onclick = () => applyGroup(g);
  });
}

function groupCard(group) {
  const knobs = spec.filter((k) => k.group === group);
  const act = GROUP_ACTION[group];
  return `<div class="set-group">
    <h3>${escapeHtml(group)}</h3>
    ${knobs.map(knob).join("")}
    <div class="set-foot">
      <span class="muted">${act ? act.note : ""}</span>
      <button class="btn" data-group="${escapeHtml(group)}">${act ? act.label : "Save"}</button>
    </div></div>`;
}

function knob(k) {
  const v = values[k.key] != null ? values[k.key] : k.default;
  return `<div class="knob">
    <label>${escapeHtml(k.label)}</label>
    <input type="range" data-k="${k.key}" min="${k.min}" max="${k.max}" step="${k.step}" value="${v}">
    <input type="number" data-k="${k.key}" min="${k.min}" max="${k.max}" step="${k.step}" value="${v}">
  </div>`;
}

function putValues() {
  return fetch(`/api/p/${slug}/settings`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }),
  }).then((r) => r.json());
}

async function saveOnly() {
  await putValues();
  toast("Settings saved");
}

async function applyGroup(group) {
  await putValues();
  const act = GROUP_ACTION[group];
  if (!act) { toast("Saved"); return; }
  const r = await post(`/api/p/${slug}/run`, { affects: act.affects });
  if (!r.ok) return toast(r.msg || "could not start", true);
  toast(`Saved — ${act.affects} started`);
  location.hash = `#/p/${slug}/run`;
}
