const DEFAULT_TIMEOUT = 15000;
// CSRF token injected into index.html by the server; required on mutating requests.
const TOKEN = (typeof window !== "undefined" && window.ATELIER_TOKEN) || "";

export async function api(p, o) {
  o = o || {};
  const ctrl = new AbortController();
  const ms = o.timeout != null ? o.timeout : DEFAULT_TIMEOUT;
  const tid = setTimeout(() => ctrl.abort(), ms);
  let res;
  try {
    res = await fetch(p, { ...o, headers: { ...(o.headers || {}), "X-Atelier-Token": TOKEN }, signal: ctrl.signal });
  } catch (e) {
    clearTimeout(tid);
    if (e && e.name === "AbortError") throw new Error(`Request timed out: ${p}`);
    throw e;
  }
  clearTimeout(tid);
  if (!res.ok) {
    // don't try to JSON-parse HTML error pages
    let detail = "";
    try { detail = (await res.text()).slice(0, 200); } catch {}
    const err = new Error(`HTTP ${res.status} on ${p}${detail ? ` — ${detail}` : ""}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const post = (p, b) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) });
export const del = (p) => api(p, { method: "DELETE" });

// Retry idempotent GETs up to 2x with 400ms backoff. Never used for mutating verbs.
export async function getRetry(p, o) {
  let last;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      return await api(p, o);
    } catch (e) {
      last = e;
      if (attempt < 2) await new Promise((r) => setTimeout(r, 400));
    }
  }
  throw last;
}

export const pct = (v) => (v == null ? "–" : Math.round(v * 100) + "%");
export const base = (p) => String(p || "").split("/").pop();
export function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
export function toast(msg, err) {
  const w = document.getElementById("toasts");
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  const dismiss = () => { t.style.opacity = "0"; setTimeout(() => t.remove(), 300); };
  if (err) {
    // sticky: stays until clicked
    t.classList.add("sticky");
    t.title = "Click to dismiss";
    t.addEventListener("click", dismiss);
  } else {
    setTimeout(dismiss, 3000);
  }
  w.appendChild(t);
}

// ---- offline / online banner ----
function ensureNetBanner() {
  let b = document.getElementById("net-banner");
  if (!b) {
    b = document.createElement("div");
    b.id = "net-banner";
    b.className = "net-banner hidden";
    b.textContent = "You are offline — changes can’t be saved until the connection returns.";
    document.body.appendChild(b);
  }
  return b;
}
function setOffline(off) {
  const b = ensureNetBanner();
  b.classList.toggle("hidden", !off);
}
window.addEventListener("offline", () => setOffline(true));
window.addEventListener("online", () => setOffline(false));
// reflect initial state on load
if (typeof navigator !== "undefined" && navigator.onLine === false) {
  if (document.body) setOffline(true);
  else window.addEventListener("DOMContentLoaded", () => setOffline(true));
}
