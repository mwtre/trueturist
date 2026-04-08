#!/usr/bin/env python3
"""Audit IATA → TripAdvisor geo → Xotelo /list for DEFAULT_DEST_CODES.

Writes CSV to stdout: iata,geo,total_count,error

Example:
  cd flight-explorer && python scripts/audit_ta_geo_xotelo.py
  python scripts/audit_ta_geo_xotelo.py -o /tmp/xotelo_audit.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.default_dest_codes import DEFAULT_DEST_CODES
from app.ta_geo import tripadvisor_location_key

BASE = "https://data.xotelo.com/api"
USER_AGENT = "flight-explorer-audit-ta-geo/1.0"


def get_list(location_key: str, *, limit: int = 5) -> tuple[int | None, str | None]:
    lim = max(1, min(limit, 100))
    url = f"{BASE}/list?{urllib.parse.urlencode({'location_key': location_key, 'offset': '0', 'limit': str(lim), 'sort': 'best_value'})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data: dict = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
        return None, str(e)

    if data.get("error"):
        return None, str(data["error"])
    res = data.get("result") or {}
    total = res.get("total_count")
    if total is None:
        t: int | None = None
    else:
        try:
            t = int(total)
        except (TypeError, ValueError):
            t = None
    return t, None


def main() -> int:
    p = argparse.ArgumentParser(description="Audit TA geo keys vs Xotelo /list")
    p.add_argument("-o", "--output", type=Path, help="Write CSV file (default: stdout)")
    p.add_argument("--limit", type=int, default=5, help="/list limit (max 100)")
    p.add_argument("--max", type=int, default=None, help="Only first N airports from the default list (debug)")
    args = p.parse_args()

    codes = DEFAULT_DEST_CODES
    if args.max is not None:
        codes = DEFAULT_DEST_CODES[: max(0, args.max)]

    rows: list[tuple[str, str, str, str]] = []
    for iata in codes:
        geo = tripadvisor_location_key(iata) or ""
        if not geo:
            rows.append((iata, "", "", "no_ta_geo"))
            continue
        total, err = get_list(geo, limit=args.limit)
        rows.append((iata, geo, "" if total is None else str(total), err or ""))

    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        w = csv.writer(out)
        w.writerow(["iata", "geo", "total_count", "error"])
        w.writerows(rows)
    finally:
        if args.output:
            out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
