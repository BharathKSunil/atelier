// Live run console: per-stage cards (the primary realtime view), live face grid,
// stop/re-run, and collapsible logs (SSE stream, persisted across reloads).
import { api, post, toast } from "./api.js";

let timer = null; // status poll
let slug = null;
let paused = false;
let es = null; // log EventSource
let lastSeq = 0; // highest log line seq seen (cursor)

export function mountRun(s) {
  slug = s;
  paused = false;
  lastSeq = 0;
  const logEl = document.getElementById("run-log");
  if (logEl) logEl.textContent = "";

  document.getElementById("run-again").onclick = async () => {
    try {
      await post(`/api/p/${slug}/run`, {});
    } catch (e) {
      toast(e && e.status === 409 ? "A run is already in progress" : "Could not start run", true);
      return;
    }
    lastSeq = 0;
    start();
  };

  const stopBtn = document.getElementById("run-stop");
  if (stopBtn)
    stopBtn.onclick = async () => {
      stopBtn.disabled = true;
      try {
        const r = await post(`/api/p/${slug}/run/stop`, {});
        toast(r.msg || "Stopping…");
      } catch {
        toast("Could not stop the run", true);
      }
      setTimeout(() => {
        stopBtn.disabled = false;
      }, 1500);
    };

  const pauseBtn = document.getElementById("run-pause");
  if (pauseBtn) {
    syncPauseBtn();
    pauseBtn.onclick = () => {
      paused = !paused;
      syncPauseBtn();
      if (paused) {
        stopStream();
        clearTimeout(timer);
        timer = null;
      } else start();
    };
  }
  start();
}

export function unmountRun() {
  clearTimeout(timer);
  timer = null;
  stopStream();
}

function syncPauseBtn() {
  const b = document.getElementById("run-pause");
  if (b) {
    b.textContent = paused ? "Resume updates" : "Pause updates";
    b.classList.toggle("accent", paused);
  }
}

function stopStream() {
  if (es) {
    es.close();
    es = null;
  }
}

async function start() {
  if (paused) return;
  await seedLog(); // survive a mid-run reload: replay everything buffered so far
  openStream();
  poll();
}

// ---- log: seed (full buffer) + SSE stream (incremental) + poll fallback ----
async function seedLog() {
  const me = slug;
  let d;
  try {
    d = await api(`/api/p/${me}/run/log?since=0`);
  } catch {
    return;
  }
  if (slug !== me) return;
  const log = document.getElementById("run-log");
  const lines = d.lines || [];
  log.textContent = lines.map((l) => l[1]).join("\n");
  if (lines.length) lastSeq = lines[lines.length - 1][0];
  log.scrollTop = log.scrollHeight;
}

function openStream() {
  stopStream();
  if (typeof EventSource === "undefined") return; // poll() fallback pulls logs instead
  const me = slug;
  es = new EventSource(`/api/p/${me}/run/stream?since=${lastSeq}`);
  es.onmessage = (ev) => {
    if (slug !== me) {
      stopStream();
      return;
    }
    if (ev.lastEventId) lastSeq = Math.max(lastSeq, +ev.lastEventId);
    try {
      appendLog(JSON.parse(ev.data));
    } catch {}
  };
  es.addEventListener("end", () => stopStream());
  es.onerror = () => stopStream(); // poll() fallback takes over
}

function appendLog(text) {
  const log = document.getElementById("run-log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 24;
  log.textContent += (log.textContent ? "\n" : "") + text;
  if (atBottom) log.scrollTop = log.scrollHeight;
}

async function poll() {
  if (!slug || paused) return;
  const me = slug;
  let s;
  try {
    s = await api(`/api/p/${me}/run/status`);
  } catch {
    if (slug === me && !paused) {
      clearTimeout(timer);
      timer = setTimeout(poll, 3000);
    }
    return;
  }
  if (slug !== me || paused) return;
  render(s);
  if (!es && s.seq > lastSeq) {
    // SSE unavailable/dropped: catch up via polling
    try {
      const d = await api(`/api/p/${me}/run/log?since=${lastSeq}`);
      (d.lines || []).forEach((l) => {
        lastSeq = Math.max(lastSeq, l[0]);
        appendLog(l[1]);
      });
    } catch {}
  }
  clearTimeout(timer);
  if (s.running) timer = setTimeout(poll, 1200);
}

function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60),
    r = sec % 60;
  return m ? `${m}m ${r}s` : `${r}s`;
}

const STAGE_LABEL = { index: "Index photos", cluster: "Group people", series: "Find bursts", score: "Score & pick" };
const STAGE_DESC = {
  index: "detect + embed faces",
  cluster: "cluster faces into people",
  series: "group bursts of the same moment",
  score: "pick the best face + frame",
};

function render(s) {
  const phases = s.all_phases || ["index", "cluster", "series", "score"];
  const done = new Set(s.phases_done || []);
  const timings = s.phase_timings || {};
  const failed = !s.running && !!s.error && !String(s.error).includes("stopped");
  const stopped = !s.running && !!s.error && String(s.error).includes("stopped");

  document.getElementById("run-title").textContent = s.running
    ? "Running…"
    : failed
      ? "Failed"
      : stopped
        ? "Stopped"
        : done.size
          ? "Complete"
          : "Run";
  document.getElementById("run-source").textContent = s.folder ? `Source: ${s.folder}` : "";

  // ---- stage cards: the primary realtime view (logs are secondary) ----
  let reachedCurrent = false;
  document.getElementById("run-stages").innerHTML = phases
    .map((p) => {
      let st;
      if (done.has(p)) st = "done";
      else if (s.phase === p) {
        st = s.error ? "failed" : "running";
        reachedCurrent = true;
      } else if (s.running && !reachedCurrent) st = "queued";
      else st = s.error ? "skipped" : s.running ? "queued" : done.size ? "skipped" : "queued";
      const icon = { done: "✓", running: "●", failed: "!", queued: "○", skipped: "–" }[st];

      let detail = "";
      if (p === "index" && (st === "running" || st === "done") && s.index_total) {
        const w = Math.round(((s.index_done || 0) / s.index_total) * 100);
        detail = `<div class="stage-bar"><i style="width:${w}%"></i></div>
          <span class="stage-sub">${s.index_done || 0}/${s.index_total} images${s.errors ? ` · ${s.errors} errors` : ""}</span>`;
      } else if (st === "running") {
        detail = `<div class="stage-bar indet"><i></i></div><span class="stage-sub">working…</span>`;
      } else {
        detail = `<span class="stage-sub">${STAGE_DESC[p] || ""}</span>`;
      }
      const dur = timings[p] != null ? `<span class="stage-dur">${timings[p]}s</span>` : "";
      return `<div class="stage-card ${st}">
        <div class="stage-top"><span class="stage-ico">${icon}</span>
          <span class="stage-name">${STAGE_LABEL[p] || p}</span>${dur}</div>
        ${detail}</div>`;
    })
    .join("");

  // ---- one-line summary ----
  const statusTxt = s.running
    ? `Running: ${STAGE_LABEL[s.phase] || s.phase || "…"}`
    : failed
      ? "Failed"
      : stopped
        ? "Stopped"
        : done.size
          ? "Complete ✓"
          : "Idle";
  const parts = [];
  if (s.faces_found != null) parts.push(`${s.faces_found} faces`);
  if (s.started_at) parts.push(fmtDur((s.finished_at || Date.now() / 1000) - s.started_at));
  document.getElementById("run-counts").textContent = `${statusTxt}${parts.length ? "   " + parts.join(" · ") : ""}`;

  // ---- error + collapsible logs (auto-open on failure) ----
  const err = document.getElementById("run-error");
  if (s.error) {
    err.textContent = s.error;
    err.classList.remove("hidden");
  } else err.classList.add("hidden");
  const det = document.getElementById("run-error-detail");
  if (det) {
    if (s.error_detail) {
      det.textContent = s.error_detail;
      det.classList.remove("hidden");
    } else det.classList.add("hidden");
  }
  if (s.error) {
    const logs = document.getElementById("run-logs");
    if (logs) logs.open = true;
  }

  document.getElementById("run-stop").classList.toggle("hidden", !s.running);
  document.getElementById("run-again").classList.toggle("hidden", s.running);

  document.getElementById("live-face-count").textContent = s.faces_found || 0;
  document.getElementById("live-face-grid").innerHTML = (s.recent_face_ids || [])
    .map((id) => `<img loading="lazy" src="/api/p/${slug}/thumb/${id}" alt="Recently detected face">`)
    .join("");
}
