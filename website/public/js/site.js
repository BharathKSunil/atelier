/* ============================================================
   Atelier site — nav, scroll reveals, copy, decorative imagery.
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
        entries.forEach((e, i) => {
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

  // ── image fallback (warm gradient if a stock image 404s) ──
  const fallback = (img) => {
    img.style.visibility = "hidden";
    const host = img.parentElement;
    if (host) host.style.background = "linear-gradient(135deg,#2a241b,#1a1611 70%)";
  };

  // ── hero contact-sheet (decorative) ──────────────────────
  $$(".sheet-frame").forEach((fr, i) => {
    const seed = fr.dataset.seed || `s${i}`;
    const url = `https://picsum.photos/seed/atelier-${seed}/300/200`;
    const probe = new Image();
    probe.onload = () => (fr.style.backgroundImage = `url("${url}")`);
    probe.onerror = () => (fr.style.background = "linear-gradient(135deg,#2a241b,#15110b)");
    probe.src = url;
  });

  // ── people shelf ─────────────────────────────────────────
  const PEOPLE = [
    ["Amara", "512", 23],
    ["The Okonkwos", "418", 41],
    ["Best man", "276", 12],
    ["Priya & Dev", "390", 8],
    ["Grandfather", "164", 33],
    ["Flower girl", "98", 47],
    ["The band", "203", 5],
    ["Officiant", "71", 60],
  ];
  const shelf = $("#peopleShelf");
  if (shelf) {
    PEOPLE.forEach(([name, count, img]) => {
      const card = document.createElement("div");
      card.className = "person";
      const url = `https://i.pravatar.cc/240?img=${img}`;
      const el = document.createElement("img");
      el.className = "av";
      el.alt = name;
      el.loading = "lazy";
      el.src = url;
      el.onerror = () => {
        el.remove();
        const ph = document.createElement("div");
        ph.className = "av";
        ph.style.cssText =
          "display:grid;place-items:center;font-family:var(--display);font-size:1.6rem;color:#cda35c;background:#241f18";
        ph.textContent = name.replace(/[^A-Za-z]/g, "").slice(0, 1) || "·";
        card.prepend(ph);
      };
      const b = document.createElement("b");
      b.textContent = name;
      const s = document.createElement("span");
      s.textContent = `${count} photos`;
      card.append(el, b, s);
      shelf.appendChild(card);
    });
  }

  // ── copy install commands ────────────────────────────────
  const copyBtn = $("#copyInstall");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const text = copyBtn.dataset.copy || ""; // &#10; in the attribute is already real newlines here
      try {
        await navigator.clipboard.writeText(text);
        copyBtn.textContent = "Copied ✓";
      } catch {
        copyBtn.textContent = "Copy failed";
      }
      if (window.__atelierToast) window.__atelierToast("Copied to clipboard");
      setTimeout(() => (copyBtn.textContent = "Copy"), 1800);
    });
  }

  // expose for future use
  void fallback;
})();
