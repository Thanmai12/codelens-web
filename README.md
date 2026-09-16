# CodeLens Web

A web front end for CodeLens: upload a zipped Python project, get code-quality and hardcoded-secret findings back as a report — no local install needed by the end user.

## How it works

- **Backend**: FastAPI (`backend/main.py`). One endpoint, `POST /api/scan`, accepts a `.zip` upload, extracts it into a temp directory (with zip-slip / path-traversal protection), runs the exact same scanning engine as the CLI (`backend/codelens/`), and returns JSON. The temp directory is deleted immediately after — nothing from an upload is ever persisted to disk long-term.
- **Frontend**: plain HTML/CSS/JS (`backend/static/`), served by the same FastAPI app via `StaticFiles`, so the whole thing is one deployable service.
- **Limits**: 20 MB max upload, 2000 files max per zip (both configurable in `main.py`).

## Run it locally first (optional, to confirm it works before deploying)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Visit `http://localhost:8000`. (This step is just to sanity-check the app — it doesn't have to be your deployment.)

## Deploy — Render (recommended)

Render runs a persistent Python web service, which fits this app well (it needs to read the upload into memory and run a real scan — not a great fit for short-lived serverless functions).

1. Push this whole `codelens-web/` folder to a GitHub repo.
2. Go to [render.com](https://render.com) → **New** → **Web Service** → connect your repo.
3. Render will detect `render.yaml` automatically and pre-fill:
   - **Build command**: `pip install -r backend/requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT --app-dir backend`
4. Click **Create Web Service**. First deploy takes ~2 minutes.
5. You'll get a URL like `https://codelens.onrender.com` — that's your live web app.

No environment variables or database needed — the app is stateless.

> Free-tier Render services spin down after inactivity and take ~30s to wake on the next request. Upgrade to a paid instance if you want it always warm.

## Deploy — Railway (alternative, also easy)

1. Push to GitHub.
2. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
3. Railway reads the `Procfile` automatically. Set the root/start command to:
   `uvicorn main:app --host 0.0.0.0 --port $PORT --app-dir backend` (same as Render, if it doesn't auto-detect the Procfile).
4. Railway assigns a public URL automatically.

## Deploy — Vercel (possible, with caveats)

Vercel's Python support is via serverless functions, which have execution-time and payload-size limits and no easy way to serve a persistent FastAPI app with a mounted static folder out of the box. It **can** work if you restructure the scan endpoint as a Vercel serverless function (`api/scan.py`) and serve the static frontend as a separate static deployment — but Render/Railway are a much closer match for what this app actually needs (a real backend process). I'd only go this route if you specifically need Vercel's ecosystem (e.g., pairing with a Next.js app you already have there).

## Security notes for whoever deploys this

- Uploaded zips are extracted to a `tempfile.TemporaryDirectory()`, which is auto-deleted when the request finishes — even on error.
- Path-traversal ("zip slip") entries are rejected before extraction.
- Upload size and file-count are capped to prevent zip-bomb style abuse; tune `MAX_UPLOAD_BYTES` / `MAX_FILES` in `backend/main.py` if you need different limits.
- There's no auth on `/api/scan` — if this is going to be public, consider adding rate limiting (e.g., via a reverse proxy) since each scan does real CPU work.
