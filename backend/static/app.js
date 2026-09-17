const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const fileNameEl = document.getElementById("file-name");
const scanBtn = document.getElementById("scan-btn");
const errorBox = document.getElementById("error-box");
const loadingSection = document.getElementById("loading");
const loadingText = document.getElementById("loading-text");
const resultsSection = document.getElementById("results");

let selectedFile = null;
let currentData = null;
let activeCategory = "all";
let activeSeverity = "all";

const LOADING_MESSAGES = ["Reading files", "Walking the tree", "Checking for secrets", "Scoring complexity"];

/* ---------- Navigation ---------- */

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    document.getElementById("view-home").hidden = view !== "home";
    document.getElementById("view-history").hidden = view !== "history";
    document.getElementById("view-settings").hidden = view !== "settings";
    if (view === "history") renderHistory();
  });
});

/* ---------- Upload ---------- */

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => { if (fileInput.files.length) handleFile(fileInput.files[0]); });

function handleFile(file) {
  if (!file.name.toLowerCase().endsWith(".zip")) {
    showError("That's not a .zip file. Choose a zipped project instead.");
    return;
  }
  selectedFile = file;
  fileNameEl.textContent = `${file.name} — ${(file.size / 1024).toFixed(0)} KB`;
  scanBtn.disabled = false;
  hideError();
}

function showError(msg) { errorBox.textContent = msg; errorBox.hidden = false; }
function hideError() { errorBox.hidden = true; }

let loadingInterval = null;

scanBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  hideError();
  resultsSection.hidden = true;
  loadingSection.hidden = false;
  scanBtn.disabled = true;

  let msgIndex = 0;
  loadingText.textContent = LOADING_MESSAGES[0];
  loadingInterval = setInterval(() => {
    msgIndex = (msgIndex + 1) % LOADING_MESSAGES.length;
    loadingText.textContent = LOADING_MESSAGES[msgIndex];
  }, 1400);

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
    dropzone.classList.add("snap");
    setTimeout(() => dropzone.classList.remove("snap"), 400);
  } catch (err) {
    showError(err.message || "Something went wrong while scanning.");
  } finally {
    clearInterval(loadingInterval);
    loadingSection.hidden = true;
    scanBtn.disabled = false;
  }
});

/* ---------- Results rendering ---------- */

function renderResults(data) {
  currentData = data;
  activeCategory = "all";
  activeSeverity = "all";
  document.querySelectorAll("#filter-category .filter-btn").forEach((b) => b.classList.toggle("active", b.dataset.value === "all"));
  document.querySelectorAll("#filter-severity .filter-btn").forEach((b) => b.classList.toggle("active", b.dataset.value === "all"));

  const score = data.score || { overall: 0, security: 0, quality: 0, complexity: 0 };
  document.getElementById("score-num").textContent = score.overall;
  setBar("security", score.security);
  setBar("quality", score.quality);
  setBar("complexity", score.complexity);

  document.getElementById("stat-scanned").textContent = data.files_scanned ?? "—";
  document.getElementById("stat-analyzed").textContent = data.files_analyzed ?? "—";
  document.getElementById("stat-errors").textContent = data.files_with_errors ?? "—";
  document.getElementById("stat-total").textContent = data.summary.total;

  const sevRow = document.getElementById("severity-row");
  const sevs = [
    { key: "critical", label: "Critical", color: "var(--critical)" },
    { key: "error", label: "Error", color: "var(--error)" },
    { key: "warning", label: "Warning", color: "var(--warning)" },
    { key: "info", label: "Info", color: "var(--info)" },
  ];
  sevRow.innerHTML = sevs.map((s) => `
    <div class="sev-card" style="--sev-color:${s.color}">
      <span class="sev-num">${data.summary[s.key] || 0}</span>
      <span class="sev-label">${s.label}</span>
    </div>
  `).join("");

  applyFilters();
  resultsSection.hidden = false;
}

function setBar(name, value) {
  document.getElementById(`bar-${name}`).style.width = `${value}%`;
  document.getElementById(`num-${name}`).textContent = value;
}

document.getElementById("filter-category").addEventListener("click", (e) => {
  const btn = e.target.closest(".filter-btn");
  if (!btn) return;
  activeCategory = btn.dataset.value;
  document.querySelectorAll("#filter-category .filter-btn").forEach((b) => b.classList.toggle("active", b === btn));
  applyFilters();
});

document.getElementById("filter-severity").addEventListener("click", (e) => {
  const btn = e.target.closest(".filter-btn");
  if (!btn) return;
  activeSeverity = btn.dataset.value;
  document.querySelectorAll("#filter-severity .filter-btn").forEach((b) => b.classList.toggle("active", b === btn));
  applyFilters();
});

function applyFilters() {
  if (!currentData) return;
  const el = document.getElementById("issue-list");

  if (activeCategory === "errors") {
    const errors = currentData.parse_errors || [];
    if (!errors.length) {
      el.innerHTML = `<div class="empty">No parse errors. Every file scanned cleanly.</div>`;
      return;
    }
    el.innerHTML = errors.map((e) => `
      <div class="row">
        <span class="dot warning"></span>
        <div class="row-msg">${escapeHtml(e)}</div>
      </div>
    `).join("");
    return;
  }

  let list = currentData.issues || [];
  if (activeCategory !== "all") list = list.filter((i) => i.category === activeCategory);
  if (activeSeverity !== "all") list = list.filter((i) => i.severity === activeSeverity);
  list = [...list].sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);

  if (!list.length) {
    el.innerHTML = `<div class="empty">No issues match these filters.</div>`;
    return;
  }

  el.innerHTML = list.map((issue, idx) => `
    <div class="row" data-idx="${idx}">
      <span class="dot ${issue.severity}"></span>
      <div>
        <div class="row-loc">
          <span class="sev">${issue.severity}</span>
          <span>${escapeHtml(issue.file)}:${issue.line}</span>
          <span class="checker">${escapeHtml(issue.checker)}</span>
        </div>
        <div class="row-msg">${escapeHtml(issue.message)}</div>
      </div>
    </div>
  `).join("");

  el.querySelectorAll(".row").forEach((row, idx) => {
    row.addEventListener("click", () => openDetail(list[idx]));
  });
}

/* ---------- Detail overlay ---------- */

const overlay = document.getElementById("detail-overlay");
const detailBody = document.getElementById("detail-body");

function openDetail(issue) {
  detailBody.innerHTML = `
    <h3>${escapeHtml(issue.checker)}</h3>
    <div class="detail-loc">${escapeHtml(issue.file)}:${issue.line}</div>
    <div class="detail-field">
      <div class="detail-field-label">Message</div>
      <div class="detail-field-value">${escapeHtml(issue.message)}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">Severity</div>
      <div class="detail-field-value" style="text-transform:capitalize">${issue.severity}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">Category</div>
      <div class="detail-field-value" style="text-transform:capitalize">${issue.category}</div>
    </div>
    ${issue.why ? `<div class="detail-field"><div class="detail-field-label">Why this matters</div><div class="detail-field-value">${escapeHtml(issue.why)}</div></div>` : ""}
    ${issue.fix ? `<div class="detail-field"><div class="detail-field-label">How to fix</div><div class="detail-field-value">${escapeHtml(issue.fix)}</div></div>` : ""}
  `;
  overlay.hidden = false;
}

document.getElementById("detail-close").addEventListener("click", () => { overlay.hidden = true; });
overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.hidden = true; });

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
  } catch (e) { /* localStorage unavailable — history just won't persist */ }
}

function renderHistory() {
  const el = document.getElementById("history-list");
  let history = [];
  try { history = JSON.parse(localStorage.getItem("codelens_history") || "[]"); } catch (e) {}

  if (!history.length) {
    el.innerHTML = `<div class="empty">No scans yet. Run one from Home and it'll show up here.</div>`;
    return;
  }

  el.innerHTML = history.map((h) => `
    <div class="row">
      <span class="dot ${h.score >= 80 ? "info" : h.score >= 50 ? "warning" : "critical"}"></span>
      <div>
        <div class="row-loc">
          <span>${new Date(h.date).toLocaleString()}</span>
          <span class="checker">score ${h.score ?? "—"}/100</span>
        </div>
        <div class="row-msg">${escapeHtml(h.name)} — ${h.total} issue${h.total === 1 ? "" : "s"} (${h.security} security, ${h.quality} quality)</div>
      </div>
    </div>
  `).join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
