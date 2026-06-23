/* ============================================================
   Atelier site — nav, scroll reveals, screenshot lightbox, copy.
   ============================================================ */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // ── sticky nav state ─────────────────────────────────────
  const nav = $("#nav");
  const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 24);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  // ── mobile menu ──────────────────────────────────────────
  const toggle = $("#navToggle");
  const links = $(".nav-links");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    $$(".nav-links a").forEach((a) =>
      a.addEventListener("click", () => {
        links.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }),
    );
  }

  // ── scroll reveal ────────────────────────────────────────
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {
    $$(".reveal").forEach((n) => n.classList.add("in"));
  } else {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            const sibs = $$(".reveal", e.target.parentElement);
            const delay = Math.min(sibs.indexOf(e.target), 5) * 80;
            setTimeout(() => e.target.classList.add("in"), delay);
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );
    $$(".reveal").forEach((n) => io.observe(n));
  }

  // ── screenshot lightbox ──────────────────────────────────
  // Any figure with [data-full] opens its full-size shot. Click backdrop or
  // press Escape to close; the page scroll is locked while open.
  const lb = $("#lightbox");
  const lbImg = $("#lightboxImg");
  const lbClose = $("#lightboxClose");
  let lastFocus = null;

  const openLightbox = (src, alt) => {
    lbImg.src = src;
    lbImg.alt = alt || "";
    lb.hidden = false;
    document.body.classList.add("lb-open");
    lastFocus = document.activeElement;
    lbClose.focus();
  };
  const closeLightbox = () => {
    lb.hidden = true;
    lbImg.removeAttribute("src");
    document.body.classList.remove("lb-open");
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
  };

  $$("[data-full]").forEach((fig) => {
    const src = fig.dataset.full;
    const img = $("img", fig);
    fig.setAttribute("role", "button");
    fig.setAttribute("tabindex", "0");
    fig.setAttribute("aria-label", `View full screenshot${img ? `: ${img.alt}` : ""}`);
    const open = () => openLightbox(src, img ? img.alt : "");
    fig.addEventListener("click", open);
    fig.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });

  if (lbClose) lbClose.addEventListener("click", closeLightbox);
  if (lb)
    lb.addEventListener("click", (e) => {
      if (e.target === lb) closeLightbox();
    });
  window.addEventListener("keydown", (e) => {
    if (!lb.hidden && e.key === "Escape") closeLightbox();
  });

  // ── tiny toast ───────────────────────────────────────────
  const toastEl = $("#toast");
  const toast = (msg) => {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    setTimeout(() => toastEl.classList.remove("show"), 1800);
  };
  window.__atelierToast = toast;

  // ── copy install commands ────────────────────────────────
  const copyBtn = $("#copyInstall");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const text = copyBtn.dataset.copy || ""; // &#10; in the attribute is already real newlines here
      try {
        await navigator.clipboard.writeText(text);
        copyBtn.textContent = "Copied ✓";
        toast("Copied to clipboard");
      } catch {
        copyBtn.textContent = "Copy failed";
      }
      setTimeout(() => (copyBtn.textContent = "Copy"), 1800);
    });
  }
})();
