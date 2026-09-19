[README.md](https://github.com/user-attachments/files/32413275/README.md)
# CodeLens

A static analysis tool for Python that scans a project for **code quality** and **security** issues in one pass — hardcoded secrets, dangerous function calls, overly complex code, and structural smells. Every finding comes with a severity, a plain-English explanation of *why it matters*, and a concrete fix suggestion.

**Live demo:** https://codelens-web-vdfq.onrender.com
**Source:** https://github.com/Thanmai12/codelens-web

---

## Why this exists

Two problems, one tool:

1. **Code quality erodes silently.** Long functions, deeply nested logic, duplicated code, and unused imports build up in any codebase until they cause a bug or slow a team down.
2. **Secrets get committed by accident.** An API key or password hardcoded during debugging, forgotten, and pushed — a common, costly security incident.

CodeLens uses the same plugin architecture ESLint uses for its rules: one shared engine, many independent checkers. That lets it handle both problems with one tool instead of two.

## Features

- Upload a project as a `.zip` — no install needed to use it (a CLI also exists for local/CI use)
- 16 rules across code quality and security, each with a stable rule ID
- A quality score (0–100) computed from real findings, with a documented formula
- Real source code shown inline for every flagged file, with the exact issue line highlighted
- Filtering by category and severity, plus text search
- Scan history stored locally in your browser

## Architecture

One engine, many checkers. `engine.py` only knows how to find `.py` files and parse them once — it has no idea what any checker is looking for. Every checker in `codelens/checkers/` is an independent class that implements one method: `check(ctx) -> list[Issue]`. Adding a new rule means writing one class; nothing else in the system changes.

**How a scan flows, step by step:**

1. A `.zip` is uploaded and validated (extension, size, entry count).
2. It's safely extracted — zip-slip and zip-bomb guarded (see Security Model below).
3. The engine walks the extracted project and collects every `.py` file.
4. Each file is read once and parsed once into an AST.
5. Every checker runs against that file's AST (or raw text, for checkers that don't need a tree).
6. One checker — duplicate-code detection — runs a second pass afterward, comparing function bodies *across* all files.
7. Each issue gets a rule ID, a severity, and a why/fix explanation.
8. Three sub-scores and an overall score are computed.
9. A single validated JSON response is returned; the temp directory is deleted immediately.

**Why AST instead of regex** for most checks: parsing Python into its real syntax tree means checkers reason about actual structure (function boundaries, call targets, nesting depth) instead of matching text patterns. Secret detection is the one exception, since secrets are inherently a text-pattern problem.

**Why the API contract is a typed schema, not a hand-built dict:** `models.py` defines `ScanResult`, `IssueModel`, `ScoreBreakdown`, and related types as Pydantic models. FastAPI validates every response against them and auto-generates a real OpenAPI schema, so the frontend and backend can't silently drift out of sync.

## Tech stack

- **Analysis engine:** Python 3, `ast` (standard library)
- **Secret detection:** `re` (regex signatures) + Shannon entropy
- **Backend:** FastAPI + Pydantic + Uvicorn
- **Frontend:** Plain HTML/CSS/JS, Tailwind (CDN), highlight.js for syntax highlighting
- **Testing:** pytest, FastAPI's `TestClient`
- **Hosting:** Render (free tier)

No paid APIs, no AI-generated findings, no database — every number on the dashboard is computed from the actual scan.

## Security model

CodeLens accepts arbitrary uploaded source code, so the tool itself is treated as security-sensitive:

- **Uploaded code is never executed.** Only `ast.parse()` (parsing, not evaluation) and regex/string inspection touch it.
- **Zip-slip protection.** Every extraction path is resolved and checked against the destination root before any file is written, rejecting entries like `../../etc/passwd`.
- **Zip-bomb protection.** Each entry's declared uncompressed size is summed from the zip's metadata and checked *before* extraction — a payload that would expand past 200MB is rejected before it's ever written to disk.
- **Resource limits.** 20MB upload cap, 2000-file cap, 60KB per-file source cap, at most 30 files' source returned per scan.
- **No persistence.** Every upload goes into a temporary directory that's deleted the moment the request finishes, success or failure.
- **Malformed input can't crash a scan.** A broken zip, a corrupt file, or a checker that throws an exception is caught and reported, not left to fail the whole request with no explanation.

## Analysis rules

**Security:**
- `SEC001` hardcoded-secret — API keys/tokens matching known formats (AWS, GitHub, Slack, JWTs, private keys), plus high-entropy strings in suspiciously-named variables
- `SEC002` dangerous-exec — `eval()` / `exec()` calls
- `SEC003` unsafe-subprocess — `subprocess.*(..., shell=True)`
- `SEC004` weak-crypto — `hashlib.md5()` / `hashlib.sha1()`
- `SEC005` unsafe-deserialization — `pickle.load()` / `pickle.loads()`
- `SEC006` sql-injection-risk — a query built with string concatenation or an f-string instead of parameters

**Quality:**
- `QUAL001` complexity — cyclomatic complexity above threshold (default 10)
- `QUAL002` long-function — function longer than 50 lines
- `QUAL003` duplicate-code — function bodies duplicated across the project
- `QUAL004` unused-imports — imported names never referenced
- `QUAL005` deep-nesting — nesting depth above 4 levels
- `QUAL006` too-many-parameters — more than 6 parameters
- `QUAL007` long-file — file longer than 500 lines
- `QUAL008` large-class — class longer than 300 lines
- `QUAL009` mutable-default-arg — `def f(x=[])`-style mutable defaults
- `QUAL010` broad-exception — bare `except:` or `except Exception:`

**On accuracy:** every security finding is a *pattern match*, not proof of an exploitable bug — wording is deliberately hedged ("potential," "may be"). Static analysis without full data-flow tracing can't know whether a given `eval()` call ever receives untrusted input.

## Scoring methodology

Security, quality, and complexity each start at 100 and lose points per issue:

- Critical issue: −20
- Error: −10
- Warning: −5
- Info: −2

Each sub-score floors at 0. The overall score is the average of the three. It's a deliberately simple, transparent formula — the goal is that anyone can trace exactly why a score is what it is, not that it perfectly predicts real-world risk.

## API

**`POST /api/scan`** — multipart upload, field name `project`, a `.zip` file.

Returns a `ScanResult` (see `models.py`) containing: a summary of issue counts, the score breakdown, the full list of issues (each with rule ID, severity, file, line, message, why, and fix), any parse errors, file counts, and the real source code for flagged files.

**`GET /api/health`** returns `{"status": "ok"}`.

The full OpenAPI schema is auto-generated at `/openapi.json`.

## Local setup

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Visit `http://localhost:8000`.

Run the tests:

```bash
pytest tests/ -v
```

## CLI

A separate, installable CLI exists for local or CI use without a browser:

```bash
pip install -e .
codelens scan ./my_project --fail-on error
```

`--fail-on` exits non-zero at or above a severity threshold, so it can gate a CI pipeline.

## Deployment

Deployed on Render as a single web service (`render.yaml` included).
Build command: `pip install -r backend/requirements.txt`
Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT` (run from the `backend` directory)

## Limitations

- Heuristic, pattern-based analysis — not a formal verifier. False negatives and rare false positives are both possible.
- No cross-function data-flow analysis — SQL-injection detection looks at *how* a query is built, not whether the interpolated value is actually attacker-controlled.
- Duplicate-code detection compares AST structure, not semantic equivalence — renamed-variable clones may be missed.
- Scan history is per-browser, not shared across devices or team members.

## Possible future work

- Per-file breakdown in the dashboard
- Configurable thresholds and inline suppression comments
- Before/after comparison between two scans
- Scanning a GitHub repo URL directly instead of requiring a zip upload
