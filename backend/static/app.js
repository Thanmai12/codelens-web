// Function triggered when user clicks an issue card on the left panel
function selectIssue(issueData, scanResponse) {
    const filePath = issueData.file;
    const lineNumber = issueData.line;
    
    // 1. Get the source code for this file from the response payload
    const sourceCode = scanResponse.sources[filePath];
    
    const codeViewer = document.getElementById("code-viewer");
    const fileHeader = document.getElementById("active-file-name");

    if (!sourceCode) {
        if (codeViewer) {
            codeViewer.innerHTML = `<div class="p-4 text-slate-400">Source code unavailable for ${filePath}</div>`;
        }
        return;
    }

    // 2. Update header title
    if (fileHeader) {
        fileHeader.textContent = filePath;
    }

    // 3. Split source code into lines and format with line numbers
    const lines = sourceCode.split("\n");
    const formattedCode = lines.map((lineText, index) => {
        const currentLineNum = index + 1;
        const isTargetLine = currentLineNum === lineNumber;
        const lineClass = isTargetLine ? "bg-red-950/60 border-l-4 border-red-500 font-bold" : "";
        
        return `<div class="flex px-4 py-0.5 ${lineClass}">
            <span class="w-12 text-slate-600 select-none text-right pr-4">${currentLineNum}</span>
            <span class="text-slate-200 font-mono whitespace-pre">${escapeHtml(lineText)}</span>
        </div>`;
    }).join("");

    if (codeViewer) {
        codeViewer.innerHTML = formattedCode;
        
        // 4. Auto-scroll to target error line
        const targetElement = codeViewer.children[lineNumber - 1];
        if (targetElement) {
            targetElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
}

function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
