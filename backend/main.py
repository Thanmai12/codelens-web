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

        # Report paths relative to the uploaded project root, not the temp dir
        def relativize(p: str) -> str:
            try:
                return os.path.relpath(p, extract_dir)
            except ValueError:
                return p

        # Discover files BEFORE scanning so we can always report how many
        # .py files were actually found, even if something later goes wrong.
        discovered = engine.discover_files(extract_dir)
        discovered_relative = [relativize(p) for p in discovered]

        if not discovered:
            return JSONResponse({
                "summary": {"total": 0, "quality": 0, "security": 0, "critical": 0,
                            "error": 0, "warning": 0, "info": 0},
                "issues": [],
                "parse_errors": [],
                "files_scanned": 0,
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
            # Never let an unexpected exception produce an opaque 500 with no
            # useful body — always tell the caller what files WERE found even
            # if the scan itself blew up.
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
            "files_scanned": len(discovered),
            "files_list": discovered_relative,
            "checkers_run": [c.name for c in checkers],
        })


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve the frontend (index.html, app.js, style.css) from the same app so
# the whole thing deploys as one web service.
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
