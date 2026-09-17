const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const fileNameEl = document.getElementById("file-name");
const scanBtn = document.getElementById("scan-btn");
const errorBox = document.getElementById("error-box");
const loadingSection = document.getElementById("loading");
const loadingText = document.getElementById("loading-text");
const resultsSection = document.getElementById("results");
const summaryLine = document.getElementById("summary-line");

let selectedFile = null;

const LOADING_MESSAGES = ["Reading files", "Walking the tree", "Checking for secrets", "Scoring complexity"];

dropzone.addEventListener("click", () => fileInput.click());

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});

dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));

dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) handleFile(fileInput.files[0]);
});

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

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.hidden = false;
}

function hideError() {
  errorBox.hidden = true;
}

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

  try {
    const resp = await fetch("/api/scan", { method: "POST", body: form });
    const data = await resp.json();
    if (!resp.ok) {
      const detail = data.detail || data.error || "Scan failed.";
      const filesNote = data.files_scanned !== undefined
        ? ` (${data.files_scanned} files were found before the crash)` : "";
      throw new Error(detail + filesNote);
    }
    renderResults(data);
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

function renderResults(data) {
  const { summary, issues, parse_errors, files_scanned, files_list, debug } = data;

  let html = `<span class="big">${summary.total}</span> issue${summary.total === 1 ? "" : "s"} found: `
    + `<span class="big">${summary.security}</span> security, <span class="big">${summary.quality}</span> quality`
    + (summary.critical ? `, <span class="big" style="color:var(--critical)">${summary.critical}</span> critical` : "") + ".";

  if (files_scanned !== undefined) {
    html += `<br><span style="color:var(--muted)">Scanned ${files_scanned} Python file${files_scanned === 1 ? "" : "s"}.</span>`;
  }
  if (debug) {
    html += `<br><span style="color:var(--muted)">${escapeHtml(debug)}</span>`;
  }
  if (files_list && files_list.length) {
    html += `<span class="files-toggle" id="files-toggle">Show scanned files (${files_list.length})</span>
      <div class="files-list" id="files-list-box" hidden>${files_list.map(escapeHtml).join("<br>")}</div>`;
  }
  summaryLine.innerHTML = html;

  const toggle = document.getElementById("files-toggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const box = document.getElementById("files-list-box");
      box.hidden = !box.hidden;
      toggle.textContent = box.hidden ? `Show scanned files (${files_list.length})` : "Hide scanned files";
    });
  }

  const security = (issues || []).filter((i) => i.category === "security")
    .sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);
  const quality = (issues || []).filter((i) => i.category === "quality")
    .sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);

  renderLedger("tab-security", security, "No security findings. Nothing hardcoded that looks like a secret.");
  renderLedger("tab-quality", quality, "No quality findings. Nothing over threshold.");
  renderErrorLedger("tab-errors", parse_errors || []);

  resultsSection.hidden = false;
}

function renderLedger(containerId, list, emptyMsg) {
  const el = document.getElementById(containerId);
  if (!list.length) {
    el.innerHTML = `<div class="empty">${emptyMsg}</div>`;
    return;
  }
  el.innerHTML = list.map((issue) => `
    <div class="row">
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
}

function renderErrorLedger(containerId, errors) {
  const el = document.getElementById(containerId);
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
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".ledger").forEach((c) => (c.hidden = true));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).hidden = false;
  });
});
