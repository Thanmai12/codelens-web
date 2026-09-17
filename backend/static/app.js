const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const fileNameEl = document.getElementById("file-name");
const scanBtn = document.getElementById("scan-btn");
const errorBox = document.getElementById("error-box");
const loadingSection = document.getElementById("loading");
const resultsSection = document.getElementById("results");
const summaryCard = document.getElementById("summary-card");

let selectedFile = null;

dropzone.addEventListener("click", () => fileInput.click());

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});

dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));

dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) {
    handleFile(e.dataTransfer.files[0]);
  }
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) handleFile(fileInput.files[0]);
});

function handleFile(file) {
  if (!file.name.toLowerCase().endsWith(".zip")) {
    showError("Please choose a .zip file.");
    return;
  }
  selectedFile = file;
  fileNameEl.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(0)} KB)`;
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

scanBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  hideError();
  resultsSection.hidden = true;
  loadingSection.hidden = false;
  scanBtn.disabled = true;

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
  } catch (err) {
    showError(err.message || "Something went wrong while scanning.");
  } finally {
    loadingSection.hidden = true;
    scanBtn.disabled = false;
  }
});

function renderResults(data) {
  const { summary, issues, parse_errors, files_scanned, files_list, debug } = data;

  summaryCard.innerHTML = `
    ${stat(files_scanned ?? "?", "Files scanned")}
    ${stat(summary.total, "Total")}
    ${stat(summary.security, "Security")}
    ${stat(summary.quality, "Quality")}
    ${stat(summary.critical, "Critical")}
    ${stat(summary.error, "Error")}
    ${stat(summary.warning, "Warning")}
    ${stat(summary.info, "Info")}
  `;

  if (debug) {
    summaryCard.innerHTML += `<div style="width:100%;margin-top:10px;color:var(--muted);font-size:0.85rem;">${escapeHtml(debug)}</div>`;
  }
  if (files_list && files_list.length) {
    summaryCard.innerHTML += `<details style="width:100%;margin-top:8px;">
      <summary style="cursor:pointer;color:var(--muted);font-size:0.85rem;">Files scanned (${files_list.length})</summary>
      <div style="margin-top:6px;font-family:ui-monospace,monospace;font-size:0.8rem;color:var(--muted);max-height:150px;overflow-y:auto;">
        ${files_list.map(escapeHtml).join("<br>")}
      </div>
    </details>`;
  }

  const security = issues.filter((i) => i.category === "security")
    .sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);
  const quality = issues.filter((i) => i.category === "quality")
    .sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);

  renderIssueList("tab-security", security, "No security findings 🎉");
  renderIssueList("tab-quality", quality, "No quality findings 🎉");
  renderErrorList("tab-errors", parse_errors);

  resultsSection.hidden = false;
}

function stat(num, label) {
  return `<div class="stat"><span class="num">${num}</span><span class="label">${label}</span></div>`;
}

function renderIssueList(containerId, list, emptyMsg) {
  const el = document.getElementById(containerId);
  if (!list.length) {
    el.innerHTML = `<div class="empty-state">${emptyMsg}</div>`;
    return;
  }
  el.innerHTML = list.map((issue) => `
    <div class="issue-row">
      <span class="badge ${issue.severity}">${issue.severity}</span>
      <div class="issue-body">
        <div class="loc">${escapeHtml(issue.file)}:${issue.line} — ${escapeHtml(issue.checker)}</div>
        <div class="msg">${escapeHtml(issue.message)}</div>
      </div>
    </div>
  `).join("");
}

function renderErrorList(containerId, errors) {
  const el = document.getElementById(containerId);
  if (!errors.length) {
    el.innerHTML = `<div class="empty-state">No parse errors 🎉</div>`;
    return;
  }
  el.innerHTML = errors.map((e) => `<div class="issue-row"><div class="issue-body msg">${escapeHtml(e)}</div></div>`).join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => (c.hidden = true));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).hidden = false;
  });
});
