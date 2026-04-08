"""Round-trip calendar scan: cheapest A/R in a date range using `SearchDates` (not per-day flight search)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Callable

from fli.core import resolve_airport
from fli.core.builders import build_date_search_segments
from fli.models import Airport, DateSearchFilters, MaxStops, PassengerInfo, SeatType
from fli.models.google_flights.base import TripType
from fli.search import SearchDates

from app.airport_meta import (
    country_code_for_iata,
    destination_in_eu,
    destination_in_uk_area,
    destination_outside_eu,
    is_international_leg,
)
from app.default_dest_codes import DEFAULT_DEST_CODES
from app.scanner import ScanRow

ProgressFn = Callable[[dict[str, Any]], None]


def _add_approx_months(start: str, months: int) -> str:
    """End date ~`months` calendar months after start (simple + stable)."""
    d0 = datetime.strptime(start, "%Y-%m-%d")
    d1 = d0 + timedelta(days=int(months * 30.5))
    return d1.strftime("%Y-%m-%d")


CalendarCellResult = tuple[str, ScanRow | None, bool, bool]
# code, row (if any), is_miss, skipped_not_rt


def _calendar_cell(
    client: SearchDates,
    origin: Airport,
    code: str,
    from_date: str,
    to_date: str,
    trip_days: int,
    stops: MaxStops,
) -> CalendarCellResult:
    dest = Airport[code]
    segments, trip_type = build_date_search_segments(
        origin,
        dest,
        from_date,
        trip_duration=trip_days,
        is_round_trip=True,
    )
    if trip_type != TripType.ROUND_TRIP:
        return code, None, False, True

    filters = DateSearchFilters(
        trip_type=TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=segments,
        stops=stops,
        seat_type=SeatType.ECONOMY,
        from_date=from_date,
        to_date=to_date,
        duration=trip_days,
    )

    try:
        results = client.search(filters)
    except Exception as e:
        cc = country_code_for_iata(code) or ""
        row = ScanRow(
            destination=code,
            destination_name=dest.value,
            price=0.0,
            currency="",
            stops=-1,
            duration_minutes=-1,
            departure_date="",
            return_date="",
            error=str(e),
            destination_country_code=cc.upper() if cc else "",
        )
        return code, row, False, False

    if not results:
        return code, None, True, False

    best = min(results, key=lambda x: x.price)
    dep = best.date[0].strftime("%Y-%m-%d")
    ret = best.date[1].strftime("%Y-%m-%d")
    cc = country_code_for_iata(code) or ""
    row = ScanRow(
        destination=code,
        destination_name=dest.value,
        price=float(best.price),
        currency=best.currency or "",
        stops=-1,
        duration_minutes=-1,
        departure_date=dep,
        return_date=ret,
        error=None,
        destination_country_code=cc.upper() if cc else "",
    )
    return code, row, False, False


def scan_roundtrip_best_dates(
    origin_code: str,
    *,
    from_date: str,
    months: int,
    trip_days: int,
    non_stop_only: bool = False,
    on_progress: ProgressFn | None = None,
    max_workers: int = 8,
    non_eu_only: bool = False,
    eu_only: bool = False,
    exclude_domestic: bool = False,
    exclude_uk: bool = False,
) -> list[ScanRow]:
    """For each destination, find cheapest round-trip (fixed trip length) in [from_date, +months]."""
    if months < 1 or months > 12:
        msg = "months must be 1–12"
        raise ValueError(msg)
    if trip_days < 1 or trip_days > 28:
        msg = "trip_days must be 1–28"
        raise ValueError(msg)

    to_date = _add_approx_months(from_date, months)
    origin = resolve_airport(origin_code)
    origin_iata = origin.name
    stops = MaxStops.NON_STOP if non_stop_only else MaxStops.ANY
    client = SearchDates()

    rows: list[ScanRow] = []
    rows_lock = threading.Lock()

    pending: list[str] = []
    for code in DEFAULT_DEST_CODES:
        if code == origin.name:
            if on_progress:
                on_progress({"kind": "skip", "destination": code, "reason": "same_as_origin"})
            if on_progress:
                on_progress({"kind": "progress"})
            continue
        try:
            Airport[code]
        except KeyError:
            if on_progress:
                on_progress({"kind": "skip", "destination": code, "reason": "unknown_airport_code"})
            if on_progress:
                on_progress({"kind": "progress"})
            continue
        if exclude_domestic and not is_international_leg(origin_iata, code):
            if on_progress:
                on_progress({"kind": "skip", "destination": code, "reason": "domestic"})
            if on_progress:
                on_progress({"kind": "progress"})
            continue
        if non_eu_only and not destination_outside_eu(code):
            if on_progress:
                on_progress({"kind": "skip", "destination": code, "reason": "eu_destination"})
            if on_progress:
                on_progress({"kind": "progress"})
            continue
        if eu_only and not destination_in_eu(code):
            if on_progress:
                on_progress({"kind": "skip", "destination": code, "reason": "non_eu_destination"})
            if on_progress:
                on_progress({"kind": "progress"})
            continue
        if exclude_uk and destination_in_uk_area(code):
            if on_progress:
                on_progress({"kind": "skip", "destination": code, "reason": "uk_destination"})
            if on_progress:
                on_progress({"kind": "progress"})
            continue
        pending.append(code)

    if not pending:
        if on_progress:
            on_progress({"kind": "done", "count": 0})
        return rows

    pool_workers = max(1, min(int(max_workers), len(pending)))

    def _run(code: str) -> CalendarCellResult:
        return _calendar_cell(client, origin, code, from_date, to_date, trip_days, stops)

    with ThreadPoolExecutor(max_workers=pool_workers) as executor:
        futures = {executor.submit(_run, c): c for c in pending}
        for fut in as_completed(futures):
            try:
                code, row, is_miss, skip_rt = fut.result()
            except Exception as e:
                code = futures[fut]
                ap_e = getattr(Airport, code, None)
                cc = country_code_for_iata(code) or ""
                row = ScanRow(
                    destination=code,
                    destination_name=ap_e.value if ap_e is not None else "",
                    price=0.0,
                    currency="",
                    stops=-1,
                    duration_minutes=-1,
                    departure_date="",
                    return_date="",
                    error=str(e),
                    destination_country_code=cc.upper() if cc else "",
                )
                is_miss = False
                skip_rt = False

            if skip_rt:
                pass
            elif is_miss:
                if on_progress:
                    on_progress({"kind": "miss", "destination": code})
            elif row is not None:
                with rows_lock:
                    rows.append(row)
                if on_progress:
                    on_progress({"kind": "row", "data": asdict(row)})

            if on_progress:
                on_progress({"kind": "progress"})

    rows.sort(key=lambda r: (r.price if r.error is None else float("inf"), r.destination))
    if on_progress:
        on_progress({"kind": "done", "count": len([r for r in rows if not r.error])})
    return rows
