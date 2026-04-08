"""Best-effort city context via Wikipedia (no API key). Cached to limit requests."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

from app.airport_meta import airport_city_for_iata, airport_subd_for_iata, country_code_for_iata

UA = "flight-explorer/1.0 (educational; contact: local)"
_MAX_EXTRACT_LEN = 380
# Larger thumbs for hero cards; city articles tend to use landmark / skyline photos.
_PI_THUMB_SIZE = 640


def _canonicalize_title(raw: str, iata: str, *, split_comma: bool = True) -> str:
    """Normalize a human label toward an English Wikipedia title."""
    t = (raw or "").strip()
    if not t:
        return iata
    t = re.sub(
        r"\s+(International\s+)?Airport\s*$",
        "",
        t,
        flags=re.I,
    ).strip()
    if split_comma and "," in t:
        t = t.split(",")[0].strip()
    if len(t) < 2:
        return iata
    return t


def _guess_wiki_title(destination_name: str, iata: str) -> str:
    return _canonicalize_title(destination_name or "", iata, split_comma=True)


def _pageimage_thumbnail(title: str) -> str | None:
    params = {
        "action": "query",
        "titles": title,
        "prop": "pageimages",
        "format": "json",
        "pithumbsize": str(_PI_THUMB_SIZE),
        "origin": "*",
    }
    url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        if page.get("missing") or int(page.get("ns", 0)) < 0:
            continue
        thumb = page.get("thumbnail") or {}
        src = thumb.get("source")
        if src and isinstance(src, str) and src.startswith("http"):
            return src
    return None


def _opensearch_titles(query: str, *, limit: int = 6) -> list[str]:
    params = {
        "action": "opensearch",
        "search": query,
        "limit": str(limit),
        "namespace": "0",
        "format": "json",
        "origin": "*",
    }
    url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return []

    if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
        return [str(t).strip() for t in data[1] if isinstance(t, str) and str(t).strip()]
    return []


def _wiki_image_search_chain(destination_name: str, iata: str) -> str | None:
    """Try airport city first (iconic photos), then airline name guess, then light tourism search."""
    seen_key: set[str] = set()
    chain: list[str] = []

    def _dedup_push(title: str) -> None:
        t = title.strip()
        if len(t) < 2:
            return
        k = t.casefold()
        if k in seen_key:
            return
        seen_key.add(k)
        chain.append(t)

    code = iata.upper()
    city = airport_city_for_iata(code)
    if city:
        _dedup_push(_canonicalize_title(city, code, split_comma=True))

    cc = country_code_for_iata(code) or ""
    if cc == "US":
        subd = airport_subd_for_iata(code)
        if city and subd:
            _dedup_push(_canonicalize_title(f"{city}, {subd}", code, split_comma=False))

    _dedup_push(_guess_wiki_title(destination_name, code))

    for title in chain:
        img = _pageimage_thumbnail(title)
        if img:
            return img

    # Tourism-oriented articles (beaches, districts, "Tourism in …") — bounded queries.
    seeds = [t for t in chain if t and t != code][:2]
    if not seeds:
        seeds = [_guess_wiki_title(destination_name, code)]
    base = seeds[0]
    for q in (
        f"{base} tourism",
        f"Tourism in {base}",
        f"{base} beach",
        f"{base} beaches",
    ):
        for sug in _opensearch_titles(q, limit=5):
            img = _pageimage_thumbnail(sug)
            if img:
                return img
    return None


@lru_cache(maxsize=384)
def wikipedia_thumbnail_url(destination_name: str, iata: str) -> str | None:
    """Prefer municipality / landmark articles over the airport page; larger thumbs."""
    return _wiki_image_search_chain(destination_name, iata)


@lru_cache(maxsize=384)
def wikipedia_summary_extract(destination_name: str, iata: str) -> tuple[str | None, str | None]:
    """First paragraph(s) from Wikipedia REST summary + canonical article URL, if found."""
    title = _guess_wiki_title(destination_name, iata)
    path = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None, None

    if data.get("type") in ("https://en.wikipedia.org/wiki/Help:Disambiguation", "disambiguation"):
        return None, None
    raw = data.get("extract")
    if not raw or not isinstance(raw, str):
        return None, None
    text = re.sub(r"\s+", " ", raw).strip()
    if len(text) > _MAX_EXTRACT_LEN:
        text = text[: _MAX_EXTRACT_LEN - 1].rsplit(" ", 1)[0] + "…"
    page = (data.get("content_urls") or {}).get("desktop") or {}
    wiki_url = page.get("page") if isinstance(page.get("page"), str) else None
    return text, wiki_url
