"""Multi-destination cheapest-fare scan using the local `fli` library."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from fli.core import resolve_airport
from fli.core.builders import build_flight_segments
from fli.models import (
    Airport,
    FlightSearchFilters,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
)
from fli.search import SearchFlights

from app.airport_meta import (
    country_code_for_iata,
    destination_in_eu,
    destination_in_uk_area,
    destination_outside_eu,
    is_international_leg,
)
from app.default_dest_codes import DEFAULT_DEST_CODES


@dataclass
class ScanRow:
    destination: str
    price: float
    currency: str
    stops: int
    duration_minutes: int
    departure_date: str = ""
    return_date: str = ""
    error: str | None = None
    destination_name: str = ""
    outbound_times_local: str = ""
    inbound_times_local: str = ""
    hotel_nightly_usd: float | None = None
    hotel_stay_usd: float | None = None
    hotel_ota: str | None = None
    hotel_sample_name: str | None = None
    hotel_error: str | None = None
    hotel_image_url: str | None = None
    hotel_ta_rating: float | None = None
    hotel_ta_review_count: int | None = None
    city_image_url: str | None = None
    hotel_list_price_min: float | None = None
    hotel_list_price_max: float | None = None
    hotel_accommodation_type: str | None = None
    hotel_labels: str | None = None
    hotel_mentions: str | None = None
    hotel_rates_checked: int | None = None
    #: ``ota`` = Xotelo /rates; ``list_guide`` = TA list range only (see ``app.xotelo_client``).
    hotel_quote_source: str | None = None
    #: Short plain-text lead from Wikipedia (REST summary); display-only.
    destination_blurb: str = ""
    destination_wiki_url: str = ""
    #: ISO 3166-1 alpha-2 from ``airportsdata`` (airport country).
    destination_country_code: str = ""


ProgressFn = Callable[[dict[str, Any]], None]


def _daterange_inclusive(start: str, end: str) -> list[str]:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    if e < s:
        msg = "date_to must be on or after date_from"
        raise ValueError(msg)
    out: list[str] = []
    cur = s
    while cur <= e:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _metrics_from_first_result(first: Any) -> tuple[float, str, int, int]:
    """Price, currency, stops, duration from one-way FlightResult or RT tuple."""
    if isinstance(first, tuple):
        outbound, inbound = first[0], first[1]
        price = float(outbound.price)
        cur = outbound.currency or ""
        stops = outbound.stops + inbound.stops
        duration = outbound.duration + inbound.duration
        return price, cur, stops, duration
    price = float(first.price)
    cur = first.currency or ""
    return price, cur, first.stops, first.duration


def _format_leg_local_window(fr: Any) -> str:
    """First departure → last arrival in airport-local wall time (from Google payload)."""
    legs = fr.legs
    if not legs:
        return ""
    dep = legs[0].departure_datetime
    arr = legs[-1].arrival_datetime
    return f"{dep.strftime('%Y-%m-%d %H:%M')} → {arr.strftime('%Y-%m-%d %H:%M')}"


def _scan_row_from_flight_first(
    code: str,
    first: Any,
    dep_str: str,
    ret_str: str,
) -> ScanRow:
    """Build ScanRow from cheapest flight result (one-way FlightResult or RT tuple)."""
    dest_name = Airport[code].value
    price, cur, n_stops, dur = _metrics_from_first_result(first)
    if isinstance(first, tuple):
        out_t = _format_leg_local_window(first[0])
        in_t = _format_leg_local_window(first[1])
    else:
        out_t = _format_leg_local_window(first)
        in_t = ""
    cc = country_code_for_iata(code) or ""
    return ScanRow(
        destination=code,
        destination_name=dest_name,
        price=price,
        currency=cur,
        stops=n_stops,
        duration_minutes=dur,
        departure_date=dep_str,
        return_date=ret_str,
        error=None,
        outbound_times_local=out_t,
        inbound_times_local=in_t,
        destination_country_code=cc.upper() if cc else "",
    )


def _search_grid_cell(
    search: SearchFlights,
    origin: Airport,
    code: str,
    dep_str: str,
    ret_str: str,
    *,
    round_trip: bool,
    stops: MaxStops,
) -> tuple[str, ScanRow | None, bool]:
    """Run one origin–destination–day lookup.

    Returns (code, row or None, is_miss) where is_miss means no flights (not an error).
    """
    ap = Airport[code]

    segments, trip_type = build_flight_segments(
        origin,
        ap,
        dep_str,
        return_date=ret_str if round_trip else None,
    )

    filters = FlightSearchFilters(
        trip_type=trip_type,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=segments,
        seat_type=SeatType.ECONOMY,
        stops=stops,
        sort_by=SortBy.CHEAPEST,
    )
    try:
        flights = search.search(filters)
    except Exception as e:
        cc = country_code_for_iata(code) or ""
        row = ScanRow(
            destination=code,
            destination_name=Airport[code].value,
            price=0.0,
            currency="",
            stops=-1,
            duration_minutes=-1,
            departure_date=dep_str,
            return_date=ret_str,
            error=str(e),
            destination_country_code=cc.upper() if cc else "",
        )
        return code, row, False

    if not flights:
        return code, None, True

    f0 = flights[0]
    row = _scan_row_from_flight_first(code, f0, dep_str, ret_str)
    return code, row, False


def scan_from_origin(
    origin_code: str,
    date_from: str,
    date_to: str,
    *,
    round_trip: bool = False,
    trip_days: int = 7,
    non_stop_only: bool = False,
    dest_codes: tuple[str, ...] | None = None,
    on_progress: ProgressFn | None = None,
    max_workers: int = 8,
    non_eu_only: bool = False,
    eu_only: bool = False,
    exclude_domestic: bool = False,
    exclude_uk: bool = False,
) -> list[ScanRow]:
    """Scan many destinations; for each, pick cheapest across all departure days in range.

    `max_workers` runs that many Google Flights lookups in parallel per outbound day.
    The shared `fli` client rate-limits to ~10 HTTP calls/s; very high values can cause errors.
    """
    origin = resolve_airport(origin_code)
    origin_iata = origin.name
    codes = dest_codes or DEFAULT_DEST_CODES
    stops = MaxStops.NON_STOP if non_stop_only else MaxStops.ANY
    search = SearchFlights()
    days = _daterange_inclusive(date_from, date_to)

    best_by_dest: dict[str, ScanRow] = {}
    best_lock = threading.Lock()

    for dep_str in days:
        ret_str = ""
        if round_trip:
            ret_dt = datetime.strptime(dep_str, "%Y-%m-%d") + timedelta(days=trip_days)
            ret_str = ret_dt.strftime("%Y-%m-%d")

        if on_progress:
            on_progress(
                {
                    "kind": "day_start",
                    "departure_date": dep_str,
                    "return_date": ret_str or None,
                }
            )

        pending: list[str] = []
        for code in codes:
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
                    on_progress(
                        {
                            "kind": "skip",
                            "destination": code,
                            "reason": "unknown_airport_code",
                        }
                    )
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
            continue

        pool_workers = max(1, min(int(max_workers), len(pending)))

        def _run_code(code: str) -> tuple[str, ScanRow | None, bool]:
            return _search_grid_cell(
                search,
                origin,
                code,
                dep_str,
                ret_str,
                round_trip=round_trip,
                stops=stops,
            )

        with ThreadPoolExecutor(max_workers=pool_workers) as executor:
            futures = {executor.submit(_run_code, c): c for c in pending}
            for fut in as_completed(futures):
                try:
                    code, row, is_miss = fut.result()
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
                        departure_date=dep_str,
                        return_date=ret_str,
                        error=str(e),
                        destination_country_code=cc.upper() if cc else "",
                    )
                    is_miss = False

                if is_miss:
                    if on_progress:
                        on_progress(
                            {"kind": "miss", "destination": code, "departure_date": dep_str}
                        )
                elif row is not None:
                    if row.error:
                        if on_progress:
                            on_progress({"kind": "row", "data": asdict(row)})
                    else:
                        with best_lock:
                            prev = best_by_dest.get(code)
                            if prev is None or row.price < prev.price:
                                best_by_dest[code] = row
                                if on_progress:
                                    on_progress({"kind": "row", "data": asdict(row)})

                if on_progress:
                    on_progress({"kind": "progress"})

    rows = sorted(best_by_dest.values(), key=lambda r: (r.price, r.destination))
    if on_progress:
        on_progress({"kind": "done", "count": len(rows)})
    return rows


def scan_to_json_lines(
    origin_code: str,
    date_from: str,
    date_to: str,
    *,
    round_trip: bool = False,
    trip_days: int = 7,
    non_stop_only: bool = False,
) -> str:
    """Synchronous scan returning NDJSON for scripting."""
    import io

    buf = io.StringIO()

    def _cb(payload: dict[str, Any]) -> None:
        buf.write(json.dumps(payload) + "\n")

    scan_from_origin(
        origin_code,
        date_from,
        date_to,
        round_trip=round_trip,
        trip_days=trip_days,
        non_stop_only=non_stop_only,
        on_progress=_cb,
    )
    return buf.getvalue()
