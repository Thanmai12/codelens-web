from __future__ import annotations

import os
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
from codelens.checkers.quality_extra import (
    DeepNestingChecker, TooManyParametersChecker, LongFileChecker,
    LargeClassChecker, MutableDefaultArgChecker, BroadExceptionChecker,
)
from codelens.checkers.security_extra import (
    DangerousExecChecker, UnsafeSubprocessChecker, WeakCryptoChecker,
    UnsafeDeserializationChecker, SqlInjectionChecker,
)
from codelens.engine import Engine
from codelens.scoring import compute_scores
from models import IssueModel, ScanError, ScanResult, ScanSummary, ScoreBreakdown, empty_scan_result

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
    "deep-nesting": {
        "why": "Deeply nested code is hard to read and reason about — each level of nesting multiplies the mental state a reader has to track.",
        "fix": "Use early returns/continues to flatten conditionals, or extract inner blocks into their own named functions.",
    },
    "too-many-parameters": {
        "why": "Functions with many parameters are hard to call correctly and hard to remember the order of.",
        "fix": "Group related parameters into a dataclass or config object, or split the function into smaller ones.",
    },
    "long-file": {
        "why": "Very large files usually mix multiple responsibilities, making them harder to navigate and to review changes in.",
        "fix": "Split the file along its natural seams — e.g. one module per class or per feature area.",
    },
    "large-class": {
        "why": "A large class often has too many responsibilities, which violates single-responsibility and makes it harder to test in isolation.",
        "fix": "Extract cohesive groups of methods into their own smaller classes.",
    },
    "mutable-default-arg": {
        "why": "A mutable default argument (list/dict/set) is created once, at function-definition time, and shared across every call that doesn't override it — mutating it in one call leaks into all future calls.",
        "fix": "Use `None` as the default and create the mutable object inside the function body instead.",
    },
    "broad-exception": {
        "why": "Catching every exception type (or catching and silently passing) hides real bugs and makes debugging much harder.",
        "fix": "Catch the specific exception types you actually expect, and log or handle the failure instead of silently passing.",
    },
    "dangerous-exec": {
        "why": "eval() and exec() run arbitrary code — if any part of the input can be influenced by a user, this is a direct code-execution vulnerability.",
        "fix": "Avoid eval/exec entirely; use safer alternatives like `ast.literal_eval` for data, or a proper parser/dispatch table for logic.",
    },
    "unsafe-subprocess": {
        "why": "shell=True runs the command through a shell, so any untrusted data in the command string can inject additional shell commands.",
        "fix": "Pass the command as a list of arguments and use shell=False (the default), avoiding shell interpretation entirely.",
    },
    "weak-crypto": {
        "why": "MD5 and SHA-1 have known collision weaknesses and should not be relied on anywhere security matters (passwords, signatures, integrity checks).",
        "fix": "Use SHA-256 or better for integrity/signatures, and a dedicated password-hashing algorithm (bcrypt, scrypt, or argon2) for passwords.",
    },
    "unsafe-deserialization": {
        "why": "Unpickling data can execute arbitrary code as a side effect of deserialization — it is not a safe format for untrusted input.",
        "fix": "Use a safe data format like JSON for untrusted input, or verify the source is fully trusted before unpickling.",
    },
    "sql-injection-risk": {
        "why": "Building a SQL query by concatenating or interpolating strings lets untrusted input change the query's structure, not just its data.",
        "fix": "Use parameterized queries (e.g. `cursor.execute(\"... WHERE id = %s\", (value,))`) instead of building the query string yourself.",
    },
}

# Stable rule identifiers, one per checker. These are part of the public API
# contract now (frontend and any future consumer can key off them), so once
# assigned, an ID must never be reassigned to a different checker -- only
# appended to. Numbering is sequential per category prefix, in no particular
# priority order beyond "the order these checkers were originally written."
RULE_IDS = {
    "hardcoded-secret": "SEC001",
    "complexity": "QUAL001",
    "long-function": "QUAL002",
    "duplicate-code": "QUAL003",
    "unused-imports": "QUAL004",
    "deep-nesting": "QUAL005",
    "too-many-parameters": "QUAL006",
    "long-file": "QUAL007",
    "large-class": "QUAL008",
    "mutable-default-arg": "QUAL009",
    "broad-exception": "QUAL010",
    "dangerous-exec": "SEC002",
    "unsafe-subprocess": "SEC003",
    "weak-crypto": "SEC004",
    "unsafe-deserialization": "SEC005",
    "sql-injection-risk": "SEC006",
}

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB, compressed upload size
MAX_FILES = 2000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB, guards against zip bombs
MAX_SOURCE_FILES = 30
MAX_SOURCE_BYTES = 60_000

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
    """
    Extract a zip while refusing:
      - path traversal ("zip slip") entries that would write outside dest
      - a decompression-bomb payload: a small compressed file that expands
        to an unreasonable amount of data on disk
    """
    dest_root = os.path.realpath(dest)
    total_uncompressed = 0
    for member in zf.infolist():
        member_path = os.path.realpath(os.path.join(dest, member.filename))
        if not member_path.startswith(dest_root + os.sep) and member_path != dest_root:
            raise HTTPException(400, f"Unsafe path in zip: {member.filename}")
        total_uncompressed += member.file_size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise HTTPException(
                400,
                f"Zip expands to more than {MAX_UNCOMPRESSED_BYTES // (1024*1024)} MB uncompressed — refusing to extract.",
            )
    zf.extractall(dest)


def _run_checkers():
    """One place that defines which checkers run on every scan."""
    return [
        ComplexityChecker(),
        LongFunctionChecker(),
        DuplicateCodeChecker(),
        UnusedImportsChecker(),
        SecretsChecker(),
        DeepNestingChecker(),
        TooManyParametersChecker(),
        LongFileChecker(),
        LargeClassChecker(),
        MutableDefaultArgChecker(),
        BroadExceptionChecker(),
        DangerousExecChecker(),
        UnsafeSubprocessChecker(),
        WeakCryptoChecker(),
        UnsafeDeserializationChecker(),
        SqlInjectionChecker(),
    ]


@app.post("/api/scan", response_model=ScanResult)
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

        engine = Engine(_run_checkers())

        def relativize(p: str) -> str:
            try:
                return os.path.relpath(p, extract_dir)
            except ValueError:
                return p

        discovered = engine.discover_files(extract_dir)
        discovered_relative = [relativize(p) for p in discovered]

        if not discovered:
            return empty_scan_result(
                "No .py files were found in this upload. Check that your zip "
                "actually contains Python files at some level (not just inside "
                "another zip, and not only in an excluded folder like venv/ or "
                "node_modules/)."
            )

        try:
            issues, errors = engine.scan(extract_dir)
        except Exception as e:
            # Never let an unexpected exception produce an opaque 500 with no
            # useful body — always tell the caller what files WERE found even
            # if the scan itself blew up.
            err = ScanError(
                error=f"Scan crashed: {type(e).__name__}: {e}",
                files_scanned=len(discovered),
                files_list=discovered_relative,
            )
            return JSONResponse(status_code=500, content=err.model_dump())

        result_issues: list[IssueModel] = []
        for issue in issues:
            d = asdict(issue)
            explanation = CHECKER_EXPLANATIONS.get(issue.checker, {})
            result_issues.append(IssueModel(
                rule_id=RULE_IDS.get(issue.checker, "UNKNOWN"),
                checker=d["checker"],
                category=issue.category.value,
                severity=issue.severity.value,
                file=relativize(d["file"]),
                line=d["line"],
                message=d["message"],
                snippet=d.get("snippet", ""),
                column=d.get("column", 0),
                why=explanation.get("why", ""),
                fix=explanation.get("fix", ""),
            ))

        result_errors = [
            relativize(e.split(":", 1)[0]) + ":" + e.split(":", 1)[1] if ":" in e else e
            for e in errors
        ]

        summary = ScanSummary(
            total=len(result_issues),
            quality=sum(1 for i in result_issues if i.category == "quality"),
            security=sum(1 for i in result_issues if i.category == "security"),
            critical=sum(1 for i in result_issues if i.severity == "critical"),
            error=sum(1 for i in result_issues if i.severity == "error"),
            warning=sum(1 for i in result_issues if i.severity == "warning"),
            info=sum(1 for i in result_issues if i.severity == "info"),
        )

        files_with_errors = len(result_errors)
        files_analyzed = len(discovered) - files_with_errors

        # Return real source for every file that has at least one issue, so
        # the frontend can show an actual code viewer instead of fabricated
        # code. Capped per-file and in total count so a huge project can't
        # blow up the response.
        rel_to_abs = dict(zip(discovered_relative, discovered))
        files_with_issues: list[str] = []
        for i in result_issues:
            if i.file not in files_with_issues:
                files_with_issues.append(i.file)

        sources: dict[str, str] = {}
        for rel in files_with_issues[:MAX_SOURCE_FILES]:
            abs_path = rel_to_abs.get(rel)
            if not abs_path:
                continue
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    sources[rel] = f.read(MAX_SOURCE_BYTES)
            except OSError:
                continue

        score_dict = compute_scores([i.model_dump() for i in result_issues])

        return ScanResult(
            summary=summary,
            score=ScoreBreakdown(**score_dict),
            issues=result_issues,
            parse_errors=result_errors,
            files_scanned=len(discovered),
            files_analyzed=files_analyzed,
            files_with_errors=files_with_errors,
            files_list=discovered_relative,
            checkers_run=[c.name for c in engine.checkers],
            sources=sources,
        )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve the frontend (index.html, app.js) from the same app so the whole
# thing deploys as one web service.
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
