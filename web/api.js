export const api = (p, o) => fetch(p, o).then((r) => r.json());
export const post = (p, b) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b || {}) });
export const del = (p) => api(p, { method: "DELETE" });
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
  w.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, 3000);
}
