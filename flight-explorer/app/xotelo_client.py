"""Xotelo public API (data.xotelo.com): list + rates. No API key."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, NamedTuple

BASE = "https://data.xotelo.com/api"
USER_AGENT = "flight-explorer/1.0"

# TripAdvisor list uses traveler “bubble” average (roughly 1–5); Xotelo has no official hotel-star field.
LUXURY_MIN_TA_RATING = 4.5


class BestHotelOffer(NamedTuple):
    nightly_usd: float | None
    ota: str | None
    hotel_name: str | None
    error: str | None
    hotel_image_url: str | None = None
    ta_rating: float | None = None
    ta_review_count: int | None = None
    list_price_min: float | None = None
    list_price_max: float | None = None
    accommodation_type: str | None = None
    labels: str | None = None
    mentions: str | None = None
    hotels_rates_checked: int | None = None
    #: ``ota`` = live Xotelo /rates floor; ``list_guide`` = TripAdvisor list range only (no bookable OTA returned).
    quote_source: str | None = None


def _get(path: str, params: dict[str, str]) -> dict:
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


def _min_nightly_from_rates(rates_json: dict) -> tuple[float | None, str | None]:
    """Minimum room rate across OTAs in a /rates response."""
    if rates_json.get("error"):
        return None, None
    rlist = (rates_json.get("result") or {}).get("rates") or []
    cands = [r for r in rlist if r.get("rate") is not None]
    if not cands:
        return None, None
    best = min(cands, key=lambda r: float(r["rate"]))
    return float(best["rate"]), str(best.get("name") or "")


def _rates_for_hotel(hotel_key: str, chk_in: str, chk_out: str) -> dict:
    return _get("rates", {"hotel_key": hotel_key, "chk_in": chk_in, "chk_out": chk_out})


def _join_label_list(val: object, max_items: int = 10) -> str | None:
    if not val:
        return None
    if isinstance(val, list):
        parts: list[str] = []
        for x in val[:max_items]:
            if x is None:
                continue
            s = str(x).strip()
            if s:
                parts.append(s)
        return " · ".join(parts) if parts else None
    s = str(val).strip()
    return s or None


def _parse_price_range(h: dict) -> tuple[float | None, float | None]:
    pr = h.get("price_ranges")
    if not isinstance(pr, dict):
        return None, None
    lo = pr.get("minimum")
    hi = pr.get("maximum")

    def _f(v: object) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return _f(lo), _f(hi)


def _list_min_sort_key(hotel: dict) -> float:
    """Ascending sort: cheapest TripAdvisor list minimum first; missing last."""
    lo, _ = _parse_price_range(hotel)
    return float(lo) if lo is not None else float("inf")


def _meta_from_slice(slice_hotels: list[dict]) -> dict[str, dict[str, Any]]:
    meta_by_key: dict[str, dict[str, Any]] = {}
    for h in slice_hotels:
        k = h["key"]
        rs = h.get("review_summary") or {}
        r_val = float(rs.get("rating") or 0)
        c_val = int(rs.get("count") or 0)
        img = h.get("image")
        pmin, pmax = _parse_price_range(h)
        acc = h.get("accommodation_type")
        acc_s = str(acc).strip() if acc else None
        meta_by_key[k] = {
            "name": h.get("name") or k,
            "image": str(img) if img and isinstance(img, str) and img.startswith("http") else None,
            "rating": r_val if r_val > 0 else None,
            "count": c_val if c_val > 0 else None,
            "list_price_min": pmin,
            "list_price_max": pmax,
            "accommodation_type": acc_s,
            "labels": _join_label_list(h.get("merchandising_labels")),
            "mentions": _join_label_list(h.get("mentions")),
        }
    return meta_by_key


def _offer_from_best_key(
    best_key: str | None,
    best_n: float | None,
    best_ota: str | None,
    meta_by_key: dict[str, dict[str, Any]],
    last_err: str | None,
    hotels_rates_checked: int,
) -> BestHotelOffer:
    if best_n is not None and best_key:
        meta = meta_by_key.get(best_key) or {}
        r_raw = meta.get("rating")
        c_raw = meta.get("count")
        r_out: float | None = None
        if isinstance(r_raw, (int, float)) and float(r_raw) > 0:
            r_out = float(r_raw)
        c_out: int | None = None
        if isinstance(c_raw, int) and c_raw > 0:
            c_out = c_raw
        elif isinstance(c_raw, float) and c_raw > 0:
            c_out = int(c_raw)
        lp_min = meta.get("list_price_min")
        lp_max = meta.get("list_price_max")
        if lp_min is not None and not isinstance(lp_min, (int, float)):
            lp_min = None
        if lp_max is not None and not isinstance(lp_max, (int, float)):
            lp_max = None
        return BestHotelOffer(
            best_n,
            best_ota,
            str(meta.get("name") or ""),
            None,
            meta.get("image") if isinstance(meta.get("image"), str) else None,
            r_out,
            c_out,
            float(lp_min) if lp_min is not None else None,
            float(lp_max) if lp_max is not None else None,
            meta.get("accommodation_type") if isinstance(meta.get("accommodation_type"), str) else None,
            meta.get("labels") if isinstance(meta.get("labels"), str) else None,
            meta.get("mentions") if isinstance(meta.get("mentions"), str) else None,
            hotels_rates_checked,
            "ota",
        )
    return BestHotelOffer(None, None, None, last_err or "no_rates")


def _offer_list_guide_fallback(
    slice_hotels: list[dict],
    meta_by_key: dict[str, dict[str, Any]],
    last_err: str | None,
    hotels_rates_checked: int,
) -> BestHotelOffer | None:
    """When every /rates call fails, use the lowest TripAdvisor ``price_ranges.minimum`` from the slice."""
    best_key: str | None = None
    best_lo: float | None = None
    for h in slice_hotels:
        k = h.get("key")
        if not k:
            continue
        lo, _ = _parse_price_range(h)
        if lo is None:
            continue
        v = float(lo)
        if best_lo is None or v < best_lo:
            best_lo = v
            best_key = str(k)
    if best_key is None or best_lo is None:
        return None
    meta = meta_by_key.get(best_key) or {}
    r_raw = meta.get("rating")
    c_raw = meta.get("count")
    r_out: float | None = None
    if isinstance(r_raw, (int, float)) and float(r_raw) > 0:
        r_out = float(r_raw)
    c_out: int | None = None
    if isinstance(c_raw, int) and c_raw > 0:
        c_out = c_raw
    elif isinstance(c_raw, float) and c_raw > 0:
        c_out = int(c_raw)
    lp_min = meta.get("list_price_min")
    lp_max = meta.get("list_price_max")
    return BestHotelOffer(
        best_lo,
        None,
        str(meta.get("name") or best_key),
        None,
        meta.get("image") if isinstance(meta.get("image"), str) else None,
        r_out,
        c_out,
        float(lp_min) if isinstance(lp_min, (int, float)) else best_lo,
        float(lp_max) if isinstance(lp_max, (int, float)) else None,
        meta.get("accommodation_type") if isinstance(meta.get("accommodation_type"), str) else None,
        meta.get("labels") if isinstance(meta.get("labels"), str) else None,
        meta.get("mentions") if isinstance(meta.get("mentions"), str) else None,
        hotels_rates_checked,
        "list_guide",
    )


def _nightly_for_list_sort(
    lk: str,
    chk_in: str,
    chk_out: str,
    *,
    luxury_only: bool,
    list_limit: int,
    max_properties: int,
    rate_workers: int,
    api_sort: str,
) -> BestHotelOffer:
    """Single /list (given sort) + parallel /rates on top properties."""
    try:
        lst = _get(
            "list",
            {
                "location_key": lk,
                "offset": "0",
                "limit": str(max(1, min(list_limit, 100))),
                "sort": api_sort,
            },
        )
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
        return BestHotelOffer(None, None, None, str(e))

    if lst.get("error"):
        return BestHotelOffer(None, None, None, str(lst["error"]))

    hotels = (lst.get("result") or {}).get("list") or []
    candidates: list[dict] = []
    for h in hotels:
        if not h.get("key"):
            continue
        rs = h.get("review_summary") or {}
        rating = float(rs.get("rating") or 0)
        if luxury_only and rating < LUXURY_MIN_TA_RATING:
            continue
        candidates.append(h)

    if not candidates:
        if luxury_only:
            return BestHotelOffer(None, None, None, "no_luxury_hotels")
        return BestHotelOffer(None, None, None, "no_hotels_in_list")

    if luxury_only:
        candidates.sort(
            key=lambda h: (
                float((h.get("review_summary") or {}).get("rating") or 0),
                int((h.get("review_summary") or {}).get("count") or 0),
            ),
            reverse=True,
        )
    else:
        # Ask /rates on listings that already look cheapest on TA first (sort order ≠ price).
        candidates.sort(key=_list_min_sort_key)

    slice_hotels = candidates[: max(1, max_properties)]
    keys = [h["key"] for h in slice_hotels]
    meta_by_key = _meta_from_slice(slice_hotels)

    def work(key: str) -> tuple[str, float | None, str | None, str | None]:
        try:
            data = _rates_for_hotel(key, chk_in, chk_out)
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
            return key, None, None, str(e)
        if data.get("error"):
            return key, None, None, str(data["error"])
        nightly, ota = _min_nightly_from_rates(data)
        return key, nightly, ota, None

    workers = max(1, min(rate_workers, len(keys)))
    best_n: float | None = None
    best_ota: str | None = None
    best_key: str | None = None
    last_err: str | None = None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(work, k): k for k in keys}
        for fut in as_completed(futs):
            key, nightly, ota, err = fut.result()
            if err:
                last_err = err
            if nightly is not None and ota is not None:
                if best_n is None or nightly < best_n:
                    best_n = nightly
                    best_ota = ota
                    best_key = key

    offer = _offer_from_best_key(best_key, best_n, best_ota, meta_by_key, last_err, len(keys))
    if offer.nightly_usd is not None:
        return offer
    fb = _offer_list_guide_fallback(slice_hotels, meta_by_key, last_err, len(keys))
    return fb if fb is not None else offer


def best_nightly_across_hotels(
    location_key: str,
    chk_in: str,
    chk_out: str,
    *,
    luxury_only: bool = False,
    list_limit: int = 50,
    max_properties: int = 18,
    rate_workers: int = 8,
) -> BestHotelOffer:
    """Best OTA nightly USD across several listed properties (parallel /rates).

    Second pass uses a different TA ``sort`` and a wider /list window when the first pass
    does not return a **live OTA** floor — different orderings surface different bookable rates.
    """
    lk = location_key if location_key.startswith("g") else f"g{location_key}"
    primary_sort = "popularity" if luxury_only else "best_value"
    alt_sort = "popularity" if primary_sort == "best_value" else "best_value"

    first = _nightly_for_list_sort(
        lk,
        chk_in,
        chk_out,
        luxury_only=luxury_only,
        list_limit=list_limit,
        max_properties=max_properties,
        rate_workers=rate_workers,
        api_sort=primary_sort,
    )
    if first.nightly_usd is not None and first.quote_source == "ota":
        return first
    if luxury_only:
        return first

    wider = min(max_properties + 10, 32)
    second = _nightly_for_list_sort(
        lk,
        chk_in,
        chk_out,
        luxury_only=luxury_only,
        list_limit=min(list_limit + 25, 100),
        max_properties=wider,
        rate_workers=rate_workers,
        api_sort=alt_sort,
    )
    ota = [
        x
        for x in (first, second)
        if x.nightly_usd is not None and x.quote_source == "ota"
    ]
    if ota:
        return min(ota, key=lambda o: float(o.nightly_usd or 0.0))
    guides = [x for x in (first, second) if x.nightly_usd is not None]
    if guides:
        return min(guides, key=lambda o: float(o.nightly_usd or 0.0))
    return first
