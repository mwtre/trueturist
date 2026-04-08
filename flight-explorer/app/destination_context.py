"""Cheap destination copy for cards: Wikipedia extract + thumb (no API key beyond WMF)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Any, Callable

from app.city_image import wikipedia_summary_extract, wikipedia_thumbnail_url
from app.scanner import ScanRow

ProgressFn = Callable[[dict[str, Any]], None]


def enrich_destination_wiki_context(
    rows: list[ScanRow],
    *,
    max_destinations: int,
    workers: int = 8,
    on_progress: ProgressFn | None = None,
) -> None:
    """Fill ``destination_blurb``, ``destination_wiki_url``, ``city_image_url`` for cheapest fares."""
    ok = [
        r
        for r in rows
        if not r.error and r.departure_date and r.return_date and len(r.departure_date) == 10 and len(r.return_date) == 10
    ]
    ok_sorted = sorted(ok, key=lambda r: (r.price, r.destination))[: max(0, max_destinations)]
    if not ok_sorted:
        return

    def _one(row: ScanRow) -> None:
        name = row.destination_name or ""
        code = row.destination
        try:
            thumb = wikipedia_thumbnail_url(name, code)
            extract, wiki_url = wikipedia_summary_extract(name, code)
            if thumb:
                row.city_image_url = thumb
            if extract:
                row.destination_blurb = extract
            if wiki_url:
                row.destination_wiki_url = wiki_url
        except Exception:  # noqa: BLE001
            pass

    w = max(1, min(workers, len(ok_sorted)))
    with ThreadPoolExecutor(max_workers=w) as pool:
        futs = {pool.submit(_one, r): r for r in ok_sorted}
        for fut in as_completed(futs):
            row = futs[fut]
            try:
                fut.result()
            except Exception:  # noqa: BLE001
                pass
            if on_progress:
                on_progress({"kind": "row", "data": asdict(row)})
