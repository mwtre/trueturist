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
