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

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_FILES = 2000

app = FastAPI(title="CodeLens")

# Same-origin in production (frontend is served by this app), but keep CORS
# open so the static frontend can also be hosted separately if needed.
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
        issues, errors = engine.scan(extract_dir)

        # Report paths relative to the uploaded project root, not the temp dir
        def relativize(p: str) -> str:
            try:
                return os.path.relpath(p, extract_dir)
            except ValueError:
                return p

        result_issues = []
        for issue in issues:
            d = asdict(issue)
            d["file"] = relativize(d["file"])
            d["category"] = issue.category.value
            d["severity"] = issue.severity.value
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

        return JSONResponse({
            "summary": summary,
            "issues": result_issues,
            "parse_errors": result_errors,
        })


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve the frontend (index.html, app.js, style.css) from the same app so
# the whole thing deploys as one web service.
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
