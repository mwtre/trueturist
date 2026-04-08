# TrueTurist

Monorepo with **`fli`** (Google Flights API wrapper) and **`flight-explorer`** (FastAPI + web UI).

## Local flight explorer

```bash
cd flight-explorer
make setup
make run
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

## GitHub Pages

The [static site](docs/index.html) is published to GitHub Pages when you push to `main` (see `.github/workflows/pages.yml`). Enable **Settings → Pages → Build and deployment → GitHub Actions** on the repository if prompted.

The Pages site is informational only; the scanner requires the Python app running (see above).

## Deploy on Render (free tier)

1. Push this repo to GitHub (e.g. `mwtre/trueturist`).
2. In [Render](https://dashboard.render.com): **New** → **Blueprint** → connect the repo → confirm `render.yaml` (or **Web Service** → **Docker**, root `Dockerfile`, context `.`).
3. After deploy, open the service **URL** (not GitHub Pages). Example: `https://trueturist.onrender.com` — try `/api/health` and `/`.

**Notes:** The free web tier **spins down** after idle traffic, so the first request can take ~1 minute. Long flight scans use streaming responses; if a platform times out, shorten the scan or use a paid instance.
