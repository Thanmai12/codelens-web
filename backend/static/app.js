const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const fileNameEl = document.getElementById("file-name");
const scanBtn = document.getElementById("scan-btn");
const errorBox = document.getElementById("error-box");
const loadingBox = document.getElementById("loading-box");
const loadingText = document.getElementById("loading-text");

let selectedFile = null;
let currentData = null;
let activeCategory = "all";
let activeSeverity = "all";
let selectedIssue = null;
let searchTerm = "";

const LOADING_MESSAGES = ["Reading files", "Walking the tree", "Checking for secrets", "Scoring complexity"];
const SEV_ORDER = { critical: 0, error: 1, warning: 2, info: 3 };

/* ---------- Navigation ---------- */

document.querySelectorAll(".nav-link").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-link").forEach((b) => b.classList.remove("active", "bg-surface-hover", "text-white"));
    btn.classList.add("active", "bg-surface-hover", "text-white");
    const view = btn.dataset.view;
    document.getElementById("view-dashboard").hidden = view !== "dashboard";
    document.getElementById("view-history").hidden = view !== "history";
    if (view === "history") renderHistory();
  });
});

/* ---------- File Upload & Dropzone Handling ---------- */

// Trigger file input click, but ignore clicks on the Analyze button
dropzone.addEventListener("click", (e) => {
  if (e.target.id === "scan-btn") return;
  fileInput.click();
});

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("border-accent-blue", "bg-surface-hover");
});

dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("border-accent-blue", "bg-surface-hover");
});

dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("border-accent-blue", "bg-surface-hover");
  if (e.dataTransfer.files.length) {
    handleFile(e.dataTransfer.files[0]);
  }
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) {
    handleFile(fileInput.files[0]);
  }
});

function handleFile(file) {
  if (!file.name.toLowerCase().endsWith(".zip")) {
    showError("That's not a .zip file. Choose a zipped project instead.");
    return;
  }
  selectedFile = file;
  fileNameEl.textContent = file.name;
  scanBtn.disabled = false;
  hideError();
}

function showError(msg) { errorBox.textContent = msg; errorBox.hidden = false; }
function hideError() { errorBox.hidden = true; }

let loadingInterval = null;

scanBtn.addEventListener("click", async (e) => {
  e.stopPropagation(); // Stop event bubbling to dropzone
  if (!selectedFile) return;
  hideError();
  scanBtn.disabled = true;
  loadingBox.hidden = false;

  let msgIndex = 0;
  loadingText.textContent = LOADING_MESSAGES[0];
  loadingInterval = setInterval(() => {
    msgIndex = (msgIndex + 1) % LOADING_MESSAGES.length;
    loadingText.textContent = LOADING_MESSAGES[msgIndex];
  }, 1200);

  const form = new FormData();
  form.append("project", selectedFile);
  const projectName = selectedFile.name;

  try {
    const resp = await fetch("/api/scan", { method: "POST", body: form });
    const data = await resp.json();
    if (!resp.ok) {
      const detail = data.detail || data.error || "Scan failed.";
      const filesNote = data.files_scanned !== undefined ? ` (${data.files_scanned} files were found before the crash)` : "";
      throw new Error(detail + filesNote);
    }
    renderResults(data);
    saveToHistory(projectName, data);
  } catch (err) {
    showError(err.message || "Something went wrong while scanning.");
  } finally {
    clearInterval(loadingInterval);
    loadingBox.hidden = true;
    scanBtn.disabled = false;
  }
});

/* ---------- Results rendering ---------- */

function renderResults(data) {
  currentData = data;
  
  // Normalize Windows paths (\) to Unix paths (/) across all returned items
  if (currentData.issues) {
    currentData.issues.forEach((i) => i.file = i.file.replace(/\\/g, "/"));
  }
  if (currentData.sources) {
    const normalizedSources = {};
    for (const [key, val] of Object.entries(currentData.sources)) {
      normalizedSources[key.replace(/\\/g, "/")] = val;
    }
    currentData.sources = normalizedSources;
  }

  activeCategory = "all";
  activeSeverity = "all";
  searchTerm = "";
  document.getElementById("issue-search").value = "";
  
  document.querySelectorAll(".cat-btn").forEach((b) => setActive(b, b.dataset.value === "all"));
  document.querySelectorAll(".sev-btn").forEach((b) => setActive(b, b.dataset.value === "all"));

  const score = data.score || { overall: 0, security: 0, quality: 0, complexity: 0 };
  document.getElementById("score-num").textContent = score.overall;
  document.getElementById("score-arc").setAttribute("stroke-dasharray", `${score.overall}, 100`);
  const label = document.getElementById("score-label");
  if (score.overall >= 85) { label.textContent = "Great health"; label.className = "text-xs font-semibold text-accent-emerald mt-0.5"; }
  else if (score.overall >= 60) { label.textContent = "Needs attention"; label.className = "text-xs font-semibold text-accent-amber mt-0.5"; }
  else { label.textContent = "At risk"; label.className = "text-xs font-semibold text-accent-rose mt-0.5"; }

  setBar("security", score.security);
  setBar("quality", score.quality);
  setBar("complexity", score.complexity);

  document.getElementById("stat-scanned").textContent = data.files_scanned ?? "—";
  document.getElementById("stat-analyzed").textContent = data.files_analyzed ?? "—";
  document.getElementById("stat-errors").textContent = data.files_with_errors ?? "—";
  document.getElementById("stat-total").textContent = data.summary.total;

  applyFilters(true); // Automatically selects and renders the top issue
}

function setBar(name, value) {
  document.getElementById(`bar-${name}`).style.width = `${value}%`;
  document.getElementById(`num-${name}`).textContent = `${value}/100`;
}

function setActive(btn, isActive) {
  btn.classList.toggle("active", isActive);
  if (btn.classList.contains("cat-btn")) {
    btn.classList.toggle("bg-accent-blue", isActive);
    btn.classList.toggle("text-white", isActive);
    btn.classList.toggle("bg-surface-card", !isActive);
    btn.classList.toggle("text-slate-400", !isActive);
  } else {
    btn.classList.toggle("bg-surface-hover", isActive);
    btn.classList.toggle("text-slate-200", isActive);
    btn.classList.toggle("bg-surface-card", !isActive);
    btn.classList.toggle("text-slate-400", !isActive);
  }
}

document.getElementById("filter-category").addEventListener("click", (e) => {
  const btn = e.target.closest(".cat-btn");
  if (!btn) return;
  activeCategory = btn.dataset.value;
  document.querySelectorAll(".cat-btn").forEach((b) => setActive(b, b === btn));
  applyFilters();
});

document.getElementById("filter-severity").addEventListener("click", (e) => {
  const btn = e.target.closest(".sev-btn");
  if (!btn) return;
  activeSeverity = btn.dataset.value;
  document.querySelectorAll(".sev-btn").forEach((b) => setActive(b, b === btn));
  applyFilters();
});

document.getElementById("issue-search").addEventListener("input", (e) => {
  searchTerm = e.target.value.toLowerCase();
  applyFilters();
});

const SEV_STYLES = {
  critical: { border: "border-l-rose-500", bg: "bg-rose-500/10", text: "text-rose-400" },
  error: { border: "border-l-amber-500", bg: "bg-amber-500/10", text: "text-amber-400" },
  warning: { border: "border-l-yellow-500", bg: "bg-yellow-500/10", text: "text-yellow-400" },
  info: { border: "border-l-blue-500", bg: "bg-blue-500/10", text: "text-blue-400" },
};

function applyFilters(autoSelectFirst = false) {
  if (!currentData) return;
  const feed = document.getElementById("issues-feed");

  if (activeCategory === "errors") {
    const errs = currentData.parse_errors || [];
    if (!errs.length) {
      feed.innerHTML = `<div class="text-slate-600 text-xs text-center mt-8">No parse errors. Every file scanned cleanly.</div>`;
      return;
    }
    feed.innerHTML = errs.map((e) => `
      <div class="p-3 rounded-r-xl border border-surface-border border-l-4 border-l-amber-500 bg-surface-panel/40">
        <p class="text-xs text-slate-300">${escapeHtml(e)}</p>
      </div>
    `).join("");
    return;
  }

  let list = currentData.issues || [];
  if (activeCategory !== "all") list = list.filter((i) => i.category === activeCategory);
  if (activeSeverity !== "all") list = list.filter((i) => i.severity === activeSeverity);
  if (searchTerm) list = list.filter((i) => i.message.toLowerCase().includes(searchTerm) || i.file.toLowerCase().includes(searchTerm) || i.checker.toLowerCase().includes(searchTerm));
  list = [...list].sort((a, b) => (SEV_ORDER[a.severity] - SEV_ORDER[b.severity]) || a.file.localeCompare(b.file));

  if (!list.length) {
    feed.innerHTML = `<div class="text-slate-600 text-xs text-center mt-8">No issues match these filters.</div>`;
    return;
  }

  if (autoSelectFirst && list.length > 0) {
    selectedIssue = list[0];
    renderCodeViewer(selectedIssue);
  }

  feed.innerHTML = list.map((issue, idx) => {
    const s = SEV_STYLES[issue.severity] || SEV_STYLES.info;
    const isSelected = selectedIssue === issue;
    return `
      <div class="issue-card p-3 rounded-r-xl border border-surface-border border-l-4 ${s.border} ${isSelected ? "bg-surface-card ring-1 ring-accent-blue/40" : "bg-surface-panel/40 hover:bg-surface-card"} transition cursor-pointer" data-idx="${idx}">
        <div class="flex items-center justify-between text-[10px] font-mono">
          <span class="uppercase font-bold tracking-wider px-1.5 py-0.5 rounded ${s.bg} ${s.text}">${issue.severity}</span>
          <span class="text-slate-500">Line ${issue.line}</span>
        </div>
        <h4 class="text-xs font-semibold text-slate-100 mt-1.5">${escapeHtml(issue.checker)}</h4>
        <p class="text-[11px] text-slate-400 mt-0.5 line-clamp-2">${escapeHtml(issue.message)}</p>
        <div class="flex items-center justify-between mt-2 pt-1.5 border-t border-surface-border/60 text-[10px] text-slate-500 font-mono">
          <span><i class="fa-regular fa-file-code mr-1"></i>${escapeHtml(issue.file)}</span>
          <span class="capitalize">${issue.category}</span>
        </div>
      </div>
    `;
  }).join("");

  feed.querySelectorAll(".issue-card").forEach((card) => {
    card.addEventListener("click", () => {
      selectedIssue = list[Number(card.dataset.idx)];
      applyFilters(false);
      renderCodeViewer(selectedIssue);
    });
  });
}

/* ---------- Code viewer ---------- */

function renderCodeViewer(issue) {
  if (!issue) return;

  const viewport = document.getElementById("code-viewport");
  const filenameEl = document.getElementById("viewer-filename");
  const statusParsed = document.getElementById("status-parsed");
  const statusLine = document.getElementById("status-lineno");

  const sourcePath = issue.file.replace(/\\/g, "/");
  const source = currentData.sources && currentData.sources[sourcePath];
  
  filenameEl.textContent = sourcePath;
  statusLine.textContent = `Line ${issue.line}`;
  statusParsed.innerHTML = `<i class="fa-solid fa-check-double mr-1.5"></i>AST parsed`;
  statusParsed.className = "flex items-center text-emerald-500";

  if (!source) {
    viewport.innerHTML = `<div class="text-slate-600 text-center mt-10">Source not available for this file.</div>`;
    return;
  }

  const lines = source.split("\n");
  const rows = lines.map((line, i) => {
    const lineNum = i + 1;
    const isTarget = lineNum === issue.line;
    const highlightClass = isTarget ? `line-highlight-${issue.severity} bg-rose-950/40 border-l-2 border-rose-500` : "";
    const escaped = escapeHtml(line) || " ";
    const banner = isTarget ? `
      <div class="mx-8 my-1 p-2 rounded bg-surface-card border border-surface-border flex items-start space-x-2 text-[11px]">
        <i class="fa-solid fa-circle-info text-accent-blue mt-0.5"></i>
        <div>
          <span class="text-slate-200 font-sans font-medium">${escapeHtml(issue.message)}</span>
          ${issue.fix ? `<div class="text-slate-400 font-sans mt-1">${escapeHtml(issue.fix)}</div>` : ""}
        </div>
      </div>
    ` : "";
    return `
      <div id="line-${lineNum}" class="flex flex-col ${highlightClass}">
        <div class="flex items-start py-0.5 px-2">
          <span class="w-8 text-right pr-3 text-slate-600 select-none text-[10px] shrink-0">${lineNum}</span>
          <pre class="flex-1 whitespace-pre-wrap m-0"><code class="language-python">${escaped}</code></pre>
        </div>
        ${banner}
      </div>
    `;
  }).join("");

  viewport.innerHTML = rows;
  viewport.querySelectorAll("code").forEach((block) => {
    if (window.hljs) hljs.highlightElement(block);
  });

  const targetElement = document.getElementById(`line-${issue.line}`);
  if (targetElement) {
    targetElement.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

/* ---------- History (localStorage) ---------- */

function saveToHistory(projectName, data) {
  try {
    const history = JSON.parse(localStorage.getItem("codelens_history") || "[]");
    history.unshift({
      name: projectName,
      date: new Date().toISOString(),
      score: data.score ? data.score.overall : null,
      total: data.summary.total,
      security: data.summary.security,
      quality: data.summary.quality,
    });
    localStorage.setItem("codelens_history", JSON.stringify(history.slice(0, 20)));
  } catch (e) { /* localStorage unavailable */ }
}

function renderHistory() {
  const el = document.getElementById("history-list");
  let history = [];
  try { history = JSON.parse(localStorage.getItem("codelens_history") || "[]"); } catch (e) {}

  if (!history.length) {
    el.innerHTML = `<div class="text-slate-600 text-xs">No scans yet. Run one from Dashboard and it'll show up here.</div>`;
    return;
  }

  el.innerHTML = history.map((h) => `
    <div class="p-3 rounded-lg border border-surface-border bg-surface-card">
      <div class="flex items-center justify-between text-[11px] font-mono text-slate-500">
        <span>${new Date(h.date).toLocaleString()}</span>
        <span>score ${h.score ?? "—"}/100</span>
      </div>
      <div class="text-xs text-slate-300 mt-1">${escapeHtml(h.name)} — ${h.total} issue${h.total === 1 ? "" : "s"} (${h.security} security, ${h.quality} quality)</div>
    </div>
  `).join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
