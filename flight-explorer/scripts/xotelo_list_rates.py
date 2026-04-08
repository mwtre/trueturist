#!/usr/bin/env python3
"""Xotelo public API: /list for a TripAdvisor location_key, then /rates for the first N hotels.

No API key on data.xotelo.com for list + rates. /search requires RapidAPI.

Example:
  python scripts/xotelo_list_rates.py --chk-in 2026-05-15 --chk-out 2026-05-18
  python scripts/xotelo_list_rates.py --location-key g188671 --chk-in 2026-06-01 --chk-out 2026-06-04 --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://data.xotelo.com/api"
USER_AGENT = "flight-explorer-xotelo-script/1.0"


def get_json(path: str, params: dict[str, str]) -> dict:
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def main() -> int:
    p = argparse.ArgumentParser(description="Xotelo: list hotels by location_key, then fetch OTA rates")
    p.add_argument(
        "--location-key",
        default="g297930",
        help="TripAdvisor location id (default: Phuket area, matches Xotelo docs example)",
    )
    p.add_argument("--chk-in", required=True, help="Check-in YYYY-MM-DD")
    p.add_argument("--chk-out", required=True, help="Check-out YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=5, help="Max hotels from /list (max API 100)")
    p.add_argument("--rates-for", type=int, default=3, help="How many listed hotels to query /rates for")
    args = p.parse_args()

    lim = max(1, min(args.limit, 100))
    n_rates = max(1, args.rates_for)

    print("GET /list …")
    lst = get_json(
        "list",
        {
            "location_key": args.location_key,
            "offset": "0",
            "limit": str(lim),
            "sort": "best_value",
        },
    )
    if lst.get("error"):
        print("list error:", lst["error"], file=sys.stderr)
        return 1
    res = lst.get("result") or {}
    hotels = res.get("list") or []
    total = res.get("total_count", "?")
    print(f"  total_count={total}, returned={len(hotels)}")
    for i, h in enumerate(hotels):
        print(f"  [{i + 1}] {h.get('name')} | key={h.get('key')}")

    if not hotels:
        return 0

    print("\nGET /rates …")
    for h in hotels[:n_rates]:
        key = h.get("key")
        name = h.get("name", key)
        if not key:
            continue
        rates_json = get_json(
            "rates",
            {"hotel_key": key, "chk_in": args.chk_in, "chk_out": args.chk_out},
        )
        print(f"\n--- {name} ---")
        if rates_json.get("error"):
            print("  error:", rates_json["error"])
            continue
        rres = rates_json.get("result") or {}
        cur = rres.get("currency", "USD")
        for r in rres.get("rates") or []:
            tax = r.get("tax")
            extra = f" (tax {tax})" if tax is not None else ""
            print(f"  {r.get('name')}: {r.get('rate')} {cur}{extra}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
