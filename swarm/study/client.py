"""Polygon.io (Massive) REST client for the baseline study.

External backtester (mentor requirement): real historical option quotes,
own list of signal dates, flow days vs ordinary days.

Point-in-time by construction: only historical aggregates are requested —
option bars for the signal day, underlying bars for the expiry settle.
No snapshot endpoints, no wall-clock defaults.

The client caches every response under data/study/cache/ so the study is
resumable and repeat pulls cost nothing. Rate limits (Developer tier is
unlimited, but 429s still happen) are retried with a short backoff.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.polygon.io"
CACHE_DIR = Path("data/study/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class PolygonClient:
    """Thin REST client with on-disk caching and 429 tolerance."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise RuntimeError("POLYGON_API_KEY is not set (add it to .env)")
        self._http = httpx.Client(base_url=BASE_URL, timeout=60)

    def _cache_path(self, path: str, params: dict) -> Path:
        slug = (path.strip("/").replace("/", "_") + "_" +
                urlencode(sorted(params.items())))
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in slug)
        return CACHE_DIR / f"{safe[:180]}.json"

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET with cache-first and bounded retries on 429/5xx and
        transport-level drops (server disconnects, timeouts)."""
        params = dict(params or {})
        params["apiKey"] = self.api_key
        cache = self._cache_path(path, params)
        if cache.exists():
            return json.loads(cache.read_text())
        attempts = 5
        for attempt in range(1, attempts + 1):
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError:
                if attempt == attempts:
                    raise
                time.sleep(2 * attempt)
                continue
            if resp.status_code == 200:
                payload = resp.json()
                cache.write_text(json.dumps(payload))
                return payload
            if resp.status_code in (429, 500, 502, 503) and attempt < attempts:
                time.sleep(2 * attempt)
                continue
            raise RuntimeError(
                f"polygon {path} -> {resp.status_code}: {resp.text[:200]}")
        raise RuntimeError(f"polygon {path}: retries exhausted")

    # ---- domain helpers -------------------------------------------------

    def stock_aggs(self, ticker: str, day_from: str, day_to: str) -> dict:
        """Underlying daily bars; the expiry settlement source."""
        return self.get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{day_from}/{day_to}",
            {"adjusted": "true", "limit": 50000})

    def contract_aggs(self, option_ticker: str, day_from: str,
                      day_to: str) -> dict:
        """Daily bars for one option contract (O:SYMYYMMDD[C/P]NNNNNNNN)."""
        return self.get(
            f"/v2/aggs/ticker/{option_ticker}/range/1/day/{day_from}/{day_to}",
            {"adjusted": "false", "limit": 50000})


def bars(payload: dict) -> list[dict]:
    """Normalized [{t(ms), o, h, l, c, v}] from an aggregates response."""
    out = []
    for r in payload.get("results") or []:
        out.append({"t": r["t"], "o": r.get("o"), "h": r.get("h"),
                    "l": r.get("l"), "c": r.get("c"), "v": r.get("v") or 0})
    return out
