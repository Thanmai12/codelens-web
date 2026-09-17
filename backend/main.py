"""
CodeLens web backend.

POST /api/scan  — multipart upload, field name "project" (a .zip of a
Python project). Extracts it into a temp dir (with zip-slip protection),
runs the same scanning engine used by the CLI, returns JSON results, then
deletes the temp dir. Nothing is persisted between requests.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from dataclasses import asdict

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from codelens.checkers.complexity import ComplexityChecker
from codelens.checkers.duplicate_code import DuplicateCodeChecker
from codelens.checkers.long_function import LongFunctionChecker
from codelens.checkers.secrets import SecretsChecker
from codelens.checkers.unused_imports import UnusedImportsChecker
from codelens.engine import Engine
from codelens.scoring import compute_scores

CHECKER_EXPLANATIONS = {
    "hardcoded-secret": {
        "why": "Hardcoded credentials can be committed to source control and exposed to anyone with repo access, including in Git history after the line is later removed.",
        "fix": "Move the value to an environment variable or a secrets manager, and rotate the credential since it may already be exposed.",
    },
    "complexity": {
        "why": "Highly branched functions are harder to read, test, and safely change — each added branch roughly doubles the number of paths through the code.",
        "fix": "Extract branches into smaller named functions, or use early returns to flatten nested conditionals.",
    },
    "long-function": {
        "why": "Long functions usually do more than one job, which makes them harder to name, test, and reuse.",
        "fix": "Split the function along its natural steps — each helper should describe one part of the process.",
    },
    "duplicate-code": {
        "why": "Duplicated logic means a bug fix or change has to be made in multiple places, and it's easy to update one copy and forget the other.",
        "fix": "Extract the shared logic into a single function both call sites use.",
    },
    "unused-imports": {
        "why": "Unused imports add noise, slow down readability, and can mask genuinely unused code.",
        "fix": "Remove the import, or add a `# noqa` comment if it's intentionally kept (e.g. for re-export).",
    },
}

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_FILES = 2000

app = FastAPI(title="CodeLens")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    """Extract a zip while refusing path traversal ('zip slip') entries."""
    dest_root = os.path.realpath(dest)
    for member in zf.infolist():
        member_path = os.path.realpath(os.path.join(dest, member.filename))
        if not member_path.startswith(dest_root + os.sep) and member_path != dest_root:
            raise HTTPException(400, f"Unsafe path in zip: {member.filename}")
    zf.extractall(dest)


@app.post("/api/scan")
async def scan_project(project: UploadFile = File(...)):
    if not project.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Please upload a .zip file of your project.")

    contents = await project.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Upload too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB).")

    with tempfile.TemporaryDirectory(prefix="codelens_") as tmpdir:
        zip_path = os.path.join(tmpdir, "upload.zip")
        with open(zip_path, "wb") as f:
            f.write(contents)

        extract_dir = os.path.join(tmpdir, "project")
        os.makedirs(extract_dir, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path) as zf:
                if len(zf.infolist()) > MAX_FILES:
                    raise HTTPException(400, f"Too many files in zip (max {MAX_FILES}).")
                _safe_extract(zf, extract_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, "That doesn't look like a valid zip file.")

        checkers = [
            ComplexityChecker(),
            LongFunctionChecker(),
            DuplicateCodeChecker(),
            UnusedImportsChecker(),
            SecretsChecker(),
        ]
        engine = Engine(checkers)

        def relativize(p: str) -> str:
            try:
                return os.path.relpath(p, extract_dir)
            except ValueError:
                return p

        discovered = engine.discover_files(extract_dir)
        discovered_relative = [relativize(p) for p in discovered]

        if not discovered:
            return JSONResponse({
                "summary": {"total": 0, "quality": 0, "security": 0, "critical": 0,
                            "error": 0, "warning": 0, "info": 0},
                "score": {"overall": 100, "security": 100, "quality": 100, "complexity": 100},
                "issues": [],
                "parse_errors": [],
                "files_scanned": 0,
                "files_analyzed": 0,
                "files_with_errors": 0,
                "files_list": [],
                "debug": (
                    "No .py files were found in this upload. Check that your zip "
                    "actually contains Python files at some level (not just inside "
                    "another zip, and not only in an excluded folder like venv/ or "
                    "node_modules/)."
                ),
            })

        try:
            issues, errors = engine.scan(extract_dir)
        except Exception as e:
           
            return JSONResponse(
                status_code=500,
                content={
                    "error": f"Scan crashed: {type(e).__name__}: {e}",
                    "files_scanned": len(discovered),
                    "files_list": discovered_relative,
                },
            )

        result_issues = []
        for issue in issues:
            d = asdict(issue)
            d["file"] = relativize(d["file"])
            d["category"] = issue.category.value
            d["severity"] = issue.severity.value
            explanation = CHECKER_EXPLANATIONS.get(issue.checker, {})
            d["why"] = explanation.get("why", "")
            d["fix"] = explanation.get("fix", "")
            result_issues.append(d)

        result_errors = [relativize(e.split(":", 1)[0]) + ":" + e.split(":", 1)[1] if ":" in e else e for e in errors]

        summary = {
            "total": len(result_issues),
            "quality": sum(1 for i in result_issues if i["category"] == "quality"),
            "security": sum(1 for i in result_issues if i["category"] == "security"),
            "critical": sum(1 for i in result_issues if i["severity"] == "critical"),
            "error": sum(1 for i in result_issues if i["severity"] == "error"),
            "warning": sum(1 for i in result_issues if i["severity"] == "warning"),
            "info": sum(1 for i in result_issues if i["severity"] == "info"),
        }

        files_with_errors = len(result_errors)
        files_analyzed = len(discovered) - files_with_errors

        return JSONResponse({
            "summary": summary,
            "score": compute_scores(result_issues),
            "issues": result_issues,
            "parse_errors": result_errors,
            "files_scanned": len(discovered),
            "files_analyzed": files_analyzed,
            "files_with_errors": files_with_errors,
            "files_list": discovered_relative,
            "checkers_run": [c.name for c in checkers],
        })


@app.get("/api/health")
async def health():
    return {"status": "ok"}



STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
