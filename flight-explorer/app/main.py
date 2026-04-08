"""FastAPI app: live SSE scan + static UI."""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.calendar_scan import scan_roundtrip_best_dates
from app.destination_context import enrich_destination_wiki_context
from app.hotel_enrich import enrich_rows_with_hotels
from app.scanner import scan_from_origin

ROOT = Path(__file__).resolve().parent.parent

MAX_OUTBOUND_RANGE_DAYS = 14
MAX_TRIP_DAYS = 28
DEFAULT_SCAN_CONCURRENCY = 8
MAX_SCAN_CONCURRENCY = 16
MAX_HOTEL_ENRICH = 40
MAX_HOTEL_DEST_PARALLEL = 12
MAX_WIKI_CONTEXT_DESTINATIONS = 56

app = FastAPI(title="Flight explorer", description="Visualize multi-destination price scan (fli)")

templates = Jinja2Templates(directory=str(ROOT / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


def _health_check_fli() -> dict:
    try:
        import fli  # noqa: F401

        try:
            v = pkg_version("flights")
        except PackageNotFoundError:
            v = getattr(fli, "__version__", None)
        return {"ok": True, "package": "flights", "version": v}
    except ImportError as e:
        return {"ok": False, "detail": str(e)}


def _health_check_xotelo(timeout_sec: float = 6.0) -> dict:
    """Light GET to public list API (same endpoint the app uses for hotels)."""
    url = "https://data.xotelo.com/api/list?location_key=g186605&offset=0&limit=1&sort=best_value"
    req = urllib.request.Request(url, headers={"User-Agent": "flight-explorer/health"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            resp.read(256)
        return {"ok": resp.status == 200, "ms": round((time.perf_counter() - t0) * 1000)}
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"ok": False, "detail": str(e)[:200], "ms": round((time.perf_counter() - t0) * 1000)}


@app.get("/api/health")
async def api_health() -> dict:
    """Process is up; ``checks`` confirms fli import and optional Xotelo reachability."""
    checks = {
        "fli_import": _health_check_fli(),
        "xotelo_reachable": _health_check_xotelo(),
    }
    fli_ok = checks["fli_import"].get("ok")
    xo_ok = checks["xotelo_reachable"].get("ok")
    if not fli_ok:
        status = "error"
    elif xo_ok:
        status = "ok"
    else:
        status = "degraded"

    return {
        "status": status,
        "service": "flight-explorer",
        "checks": checks,
        "endpoints": [
            "/ (simple UI)",
            "/explorer (advanced UI)",
            "/api/scan/stream",
            "/api/calendar/stream",
            "/api/health",
        ],
        "notes": "degraded = optional check failed (e.g. network); scans need fli. Setup: make setup in flight-explorer.",
    }


def _validate_dates(date_from: str, date_to: str) -> None:
    if len(date_from) != 10 or date_from[4] != "-" or date_from[7] != "-":
        raise HTTPException(status_code=400, detail="date_from must be YYYY-MM-DD")
    if len(date_to) != 10 or date_to[4] != "-" or date_to[7] != "-":
        raise HTTPException(status_code=400, detail="date_to must be YYYY-MM-DD")
    try:
        d0 = datetime.strptime(date_from, "%Y-%m-%d")
        d1 = datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid calendar date") from e
    if d1 < d0:
        raise HTTPException(status_code=400, detail="date_to must be on or after date_from")
    span = (d1 - d0).days + 1
    if span > MAX_OUTBOUND_RANGE_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"outbound range too large (max {MAX_OUTBOUND_RANGE_DAYS} days)",
        )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Simple trip finder for end users."""
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/explorer", response_class=HTMLResponse)
async def explorer_page(request: Request) -> HTMLResponse:
    """Full multi-panel scanner (calendar, grid, charts)."""
    return templates.TemplateResponse(request, "explorer.html", {})


def _resolve_scan_dates(
    date: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, str]:
    """Accept either (date_from + date_to) or legacy single-day `date`."""
    df = date_from.strip() if date_from else None
    dt = date_to.strip() if date_to else None
    d1 = date.strip() if date else None
    if df and dt:
        return df, dt
    if d1:
        return d1, d1
    raise HTTPException(
        status_code=422,
        detail=(
            "Missing dates: send date_from and date_to (range), or date (single day). "
            "Restart uvicorn if you still see a 'date' field error — an old process may be running."
        ),
    )


@app.get("/api/scan/stream")
async def scan_stream(
    origin: str = Query("AMS", min_length=3, max_length=3),
    date: str | None = Query(
        None,
        description="Single outbound day YYYY-MM-DD (optional if date_from/date_to are set)",
    ),
    date_from: str | None = Query(None, description="First outbound date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="Last outbound date YYYY-MM-DD"),
    round_trip: bool = Query(False, description="Round trip (A/R)"),
    trip_days: int = Query(7, ge=1, le=MAX_TRIP_DAYS, description="Days from outbound to return"),
    non_stop: bool = Query(False),
    non_eu_only: bool = Query(
        False,
        description="Only destinations outside the EU (27). Filters out intra-EU airports (e.g. AMS→DUS).",
    ),
    eu_only: bool = Query(
        False,
        description="Only destinations inside the EU (27). Mutually exclusive in practice with non_eu_only.",
    ),
    exclude_domestic: bool = Query(
        False,
        description="Skip routes where origin and destination are in the same country",
    ),
    exclude_uk: bool = Query(
        False,
        description="Skip destinations in the UK and Crown Dependencies (GB, Jersey, Guernsey, Isle of Man)",
    ),
    with_hotels: bool = Query(
        False,
        description="After flights, fetch Xotelo hotel floor price (USD) for cheapest destinations (needs RT dates)",
    ),
    hotel_top_n: int = Query(
        12,
        ge=0,
        le=MAX_HOTEL_ENRICH,
        description="How many cheapest flight destinations to enrich with hotel rates",
    ),
    hotel_five_star: bool = Query(
        False,
        description="Luxury: TripAdvisor traveler rating ≥ 4.5 only; lowest nightly among them (API has no official star field).",
    ),
    hotel_workers: int = Query(
        5,
        ge=1,
        le=MAX_HOTEL_DEST_PARALLEL,
        description="How many destinations to query Xotelo for in parallel",
    ),
    concurrency: int = Query(
        DEFAULT_SCAN_CONCURRENCY,
        ge=1,
        le=MAX_SCAN_CONCURRENCY,
        description="Parallel destination lookups (higher = faster until Google rate-limits)",
    ),
) -> StreamingResponse:
    date_from, date_to = _resolve_scan_dates(date, date_from, date_to)
    _validate_dates(date_from, date_to)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_progress(payload: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, json.dumps(payload))

    def run_scan() -> None:
        try:
            rows = scan_from_origin(
                origin.upper(),
                date_from,
                date_to,
                round_trip=round_trip,
                trip_days=trip_days,
                non_stop_only=non_stop,
                on_progress=on_progress,
                max_workers=concurrency,
                non_eu_only=non_eu_only,
                eu_only=eu_only,
                exclude_domestic=exclude_domestic,
                exclude_uk=exclude_uk,
            )
            if rows:
                enrich_destination_wiki_context(
                    rows,
                    max_destinations=min(MAX_WIKI_CONTEXT_DESTINATIONS, len(rows)),
                    workers=max(4, min(10, concurrency)),
                    on_progress=on_progress,
                )
            if with_hotels and hotel_top_n > 0 and rows:
                enrich_rows_with_hotels(
                    rows,
                    max_destinations=hotel_top_n,
                    on_progress=on_progress,
                    luxury_only=hotel_five_star,
                    destination_workers=hotel_workers,
                )
        except Exception as e:
            on_progress({"kind": "error", "detail": str(e)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def event_stream() -> AsyncIterator[bytes]:
        yield b"retry: 600000\n\n"
        task = asyncio.create_task(asyncio.to_thread(run_scan))
        try:
            while True:
                # Keep the TCP connection warm while Google Flights calls run in a thread
                # (avoids proxy/browser idle timeouts during long scans).
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                if line is None:
                    yield f"data: {json.dumps({'kind': 'complete'})}\n\n".encode()
                    break
                yield f"data: {line}\n\n".encode()
        finally:
            await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/calendar/stream")
async def calendar_stream(
    origin: str = Query("AMS", min_length=3, max_length=3),
    from_date: str = Query(..., description="First day of horizon YYYY-MM-DD"),
    months: int = Query(6, ge=1, le=12, description="Months of horizon (~30.5d each)"),
    trip_days: int = Query(7, ge=1, le=MAX_TRIP_DAYS, description="Round-trip length in days"),
    non_stop: bool = Query(False),
    non_eu_only: bool = Query(
        False,
        description="Only destinations outside the EU (27)",
    ),
    eu_only: bool = Query(
        False,
        description="Only destinations inside the EU (27)",
    ),
    exclude_domestic: bool = Query(
        False,
        description="Skip routes where origin and destination are in the same country",
    ),
    exclude_uk: bool = Query(
        False,
        description="Skip UK and Crown Dependency destinations",
    ),
    with_hotels: bool = Query(False, description="Enrich with Xotelo hotel estimates after calendar scan"),
    hotel_top_n: int = Query(12, ge=0, le=MAX_HOTEL_ENRICH),
    hotel_five_star: bool = Query(
        False,
        description="Luxury: TripAdvisor traveler rating ≥ 4.5 only; lowest nightly among them",
    ),
    hotel_workers: int = Query(
        5,
        ge=1,
        le=MAX_HOTEL_DEST_PARALLEL,
        description="Parallel Xotelo destination lookups",
    ),
    concurrency: int = Query(
        DEFAULT_SCAN_CONCURRENCY,
        ge=1,
        le=MAX_SCAN_CONCURRENCY,
        description="Parallel destination lookups (calendar graph per airport)",
    ),
) -> StreamingResponse:
    if len(from_date) != 10 or from_date[4] != "-" or from_date[7] != "-":
        raise HTTPException(status_code=400, detail="from_date must be YYYY-MM-DD")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_progress(payload: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, json.dumps(payload))

    def run_calendar() -> None:
        try:
            rows = scan_roundtrip_best_dates(
                origin.upper(),
                from_date=from_date,
                months=months,
                trip_days=trip_days,
                non_stop_only=non_stop,
                on_progress=on_progress,
                max_workers=concurrency,
                non_eu_only=non_eu_only,
                eu_only=eu_only,
                exclude_domestic=exclude_domestic,
                exclude_uk=exclude_uk,
            )
            if rows:
                enrich_destination_wiki_context(
                    rows,
                    max_destinations=min(MAX_WIKI_CONTEXT_DESTINATIONS, len(rows)),
                    workers=max(4, min(10, concurrency)),
                    on_progress=on_progress,
                )
            if with_hotels and hotel_top_n > 0 and rows:
                enrich_rows_with_hotels(
                    rows,
                    max_destinations=hotel_top_n,
                    on_progress=on_progress,
                    luxury_only=hotel_five_star,
                    destination_workers=hotel_workers,
                )
        except Exception as e:
            on_progress({"kind": "error", "detail": str(e)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def event_stream() -> AsyncIterator[bytes]:
        yield b"retry: 600000\n\n"
        task = asyncio.create_task(asyncio.to_thread(run_calendar))
        try:
            while True:
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                if line is None:
                    yield f"data: {json.dumps({'kind': 'complete'})}\n\n".encode()
                    break
                yield f"data: {line}\n\n".encode()
        finally:
            await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
