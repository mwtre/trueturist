"""After flight rows are ready, optionally enrich with Xotelo hotel floor price."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from typing import Any

from app.city_image import wikipedia_summary_extract, wikipedia_thumbnail_url
from app.scanner import ScanRow
from app.ta_geo import tripadvisor_location_key
from app.xotelo_client import BestHotelOffer, best_nightly_across_hotels

ProgressFn = Any


def _stay_nights(chk_in: str, chk_out: str) -> int:
    a = datetime.strptime(chk_in, "%Y-%m-%d")
    b = datetime.strptime(chk_out, "%Y-%m-%d")
    n = (b - a).days
    return max(1, n)


def _apply_hotel_offer(row: ScanRow, offer: BestHotelOffer) -> None:
    if offer.error:
        row.hotel_error = offer.error
        row.hotel_nightly_usd = None
        row.hotel_stay_usd = None
        row.hotel_ota = None
        row.hotel_sample_name = offer.hotel_name
        row.hotel_image_url = None
        row.hotel_ta_rating = None
        row.hotel_ta_review_count = None
        row.hotel_list_price_min = None
        row.hotel_list_price_max = None
        row.hotel_accommodation_type = None
        row.hotel_labels = None
        row.hotel_mentions = None
        row.hotel_rates_checked = None
        row.hotel_quote_source = None
        return
    row.hotel_error = None
    row.hotel_nightly_usd = offer.nightly_usd
    row.hotel_ota = offer.ota
    row.hotel_sample_name = offer.hotel_name
    row.hotel_image_url = offer.hotel_image_url
    row.hotel_ta_rating = offer.ta_rating
    row.hotel_ta_review_count = offer.ta_review_count
    row.hotel_list_price_min = offer.list_price_min
    row.hotel_list_price_max = offer.list_price_max
    row.hotel_accommodation_type = offer.accommodation_type
    row.hotel_labels = offer.labels
    row.hotel_mentions = offer.mentions
    row.hotel_rates_checked = offer.hotels_rates_checked
    row.hotel_quote_source = offer.quote_source or "ota"
    nights = _stay_nights(row.departure_date, row.return_date)
    row.hotel_stay_usd = (
        round(float(offer.nightly_usd) * nights, 2) if offer.nightly_usd is not None else None
    )


def _enrich_one_row(
    row: ScanRow,
    *,
    luxury_only: bool,
    list_limit: int,
    max_properties: int,
    rate_workers: int,
) -> None:
    """Resolve Wikipedia city thumb and Xotelo hotel in parallel to cut wall time per destination."""
    geo = tripadvisor_location_key(row.destination)

    def _wiki_thumb() -> str | None:
        try:
            return wikipedia_thumbnail_url(row.destination_name or "", row.destination)
        except Exception:  # noqa: BLE001
            return None

    def _wiki_summary() -> tuple[str | None, str | None]:
        try:
            return wikipedia_summary_extract(row.destination_name or "", row.destination)
        except Exception:  # noqa: BLE001
            return None, None

    def _hotel_offer() -> BestHotelOffer:
        if not geo:
            return BestHotelOffer(None, None, None, "no_ta_geo")
        try:
            return best_nightly_across_hotels(
                geo,
                row.departure_date,
                row.return_date,
                luxury_only=luxury_only,
                list_limit=list_limit,
                max_properties=max_properties,
                rate_workers=rate_workers,
            )
        except Exception as e:  # noqa: BLE001
            return BestHotelOffer(None, None, None, str(e))

    with ThreadPoolExecutor(max_workers=3) as inner:
        fut_w = inner.submit(_wiki_thumb)
        fut_s = inner.submit(_wiki_summary)
        fut_h = inner.submit(_hotel_offer)
        row.city_image_url = fut_w.result()
        ext, wiki_u = fut_s.result()
        if ext:
            row.destination_blurb = ext
        if wiki_u:
            row.destination_wiki_url = wiki_u
        offer = fut_h.result()
    _apply_hotel_offer(row, offer)


def enrich_rows_with_hotels(
    rows: list[ScanRow],
    *,
    max_destinations: int,
    on_progress: ProgressFn | None,
    luxury_only: bool = False,
    destination_workers: int = 5,
    list_limit: int = 60,
    max_properties: int = 20,
    rate_workers: int = 8,
) -> None:
    """Mutates rows in place; re-fires ``on_progress`` with ``kind: row`` for updated ScanRow."""
    ok = [
        r
        for r in rows
        if not r.error and r.departure_date and r.return_date and len(r.departure_date) == 10 and len(r.return_date) == 10
    ]
    ok_sorted = sorted(ok, key=lambda r: (r.price, r.destination))[: max(0, max_destinations)]

    if on_progress and ok_sorted:
        on_progress({"kind": "hotel_phase", "total": len(ok_sorted)})

    dest_w = max(1, min(destination_workers, len(ok_sorted) or 1))
    rw = min(rate_workers, max(3, 48 // dest_w))

    with ThreadPoolExecutor(max_workers=dest_w) as pool:
        futs = {
            pool.submit(
                _enrich_one_row,
                row,
                luxury_only=luxury_only,
                list_limit=list_limit,
                max_properties=max_properties,
                rate_workers=rw,
            ): row
            for row in ok_sorted
        }
        done = 0
        for fut in as_completed(futs):
            row = futs[fut]
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                row.hotel_error = str(e)
                row.hotel_nightly_usd = None
                row.hotel_stay_usd = None
                row.hotel_ota = None
                row.hotel_image_url = None
                row.hotel_ta_rating = None
                row.hotel_ta_review_count = None
                row.hotel_list_price_min = None
                row.hotel_list_price_max = None
                row.hotel_accommodation_type = None
                row.hotel_labels = None
                row.hotel_mentions = None
                row.hotel_rates_checked = None
                row.hotel_quote_source = None
            done += 1
            if on_progress:
                on_progress({"kind": "row", "data": asdict(row)})
                on_progress(
                    {
                        "kind": "hotel_progress",
                        "done": done,
                        "total": len(ok_sorted),
                        "destination": row.destination,
                    }
                )

    if on_progress:
        on_progress({"kind": "hotel_phase_done"})
