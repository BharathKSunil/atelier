// Lightweight styled confirm / prompt dialog (self-contained overlay + focus trap).
// Replaces the native window.confirm/prompt with the app's own look.
import { escapeHtml } from "./api.js";

function buildDialog({ title, message, label, value, placeholder, okLabel, cancelLabel, danger, withInput }) {
  return new Promise((resolve) => {
    const prev = document.activeElement;
    const overlay = document.createElement("div");
    overlay.className = "modal";
    overlay.innerHTML = `
      <div class="modal-box" role="dialog" aria-modal="true" tabindex="-1" style="width:420px">
        <h3>${escapeHtml(title)}</h3>
        ${message ? `<p class="confirm-msg">${message}</p>` : ""}
        ${withInput ? `<input class="confirm-name" type="text" placeholder="${escapeHtml(placeholder || "")}" value="${escapeHtml(value || "")}" aria-label="${escapeHtml(label || title)}">` : ""}
        <div class="modal-actions">
          <button class="btn ghost" data-act="cancel">${escapeHtml(cancelLabel || "Cancel")}</button>
          <button class="btn ${danger ? "accent" : ""}" data-act="ok">${escapeHtml(okLabel || "OK")}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const box = overlay.querySelector(".modal-box");
    const input = overlay.querySelector(".confirm-name");
    const okBtn = overlay.querySelector('[data-act="ok"]');
    const cancelBtn = overlay.querySelector('[data-act="cancel"]');

    const done = (result) => {
      overlay.remove();
      window.removeEventListener("keydown", onKey, true);
      if (prev && typeof prev.focus === "function" && document.contains(prev)) prev.focus();
      resolve(result);
    };
    const accept = () => done(withInput ? input.value : true);
    const cancel = () => done(withInput ? null : false);

    okBtn.onclick = accept;
    cancelBtn.onclick = cancel;
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) cancel();
    });

    const focusable = () =>
      [...box.querySelectorAll('input,button,[tabindex]:not([tabindex="-1"])')].filter((n) => !n.disabled);
    const onKey = (e) => {
      // capture-phase: stop the global Escape from also closing the modal behind us
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        cancel();
        return;
      }
      if (e.key === "Enter" && withInput && document.activeElement === input) {
        e.preventDefault();
        accept();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0],
        last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey, true);
    requestAnimationFrame(() => {
      (withInput ? input : okBtn).focus();
      if (withInput) input.select();
    });
  });
}

export function confirmDialog(opts) {
  return buildDialog({ ...opts, withInput: false });
}
export function promptDialog(opts) {
  return buildDialog({ ...opts, withInput: true });
}
