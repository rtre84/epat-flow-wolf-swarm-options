"""Persistent TradeSpec store: scans accumulate, never overwrite.

`data/specs/trade_specs.json` is upserted by `trade_id` (date_ticker) so
repeated scans build history instead of replacing it: new ids append, a
re-scan of the same date+ticker replaces the older record. Records without
a `trade_id` (e.g. the chair's empty-day object) are not specs and are
dropped on load.

Kept import-light (no crew/UW imports) so tests can use it directly:
importing `swarm.crew` spawns the UW MCP server process.
"""
from __future__ import annotations

import json
from pathlib import Path

SPEC_FILE = Path(__file__).resolve().parent.parent / "data" / "specs" / "trade_specs.json"


def load_existing(path: Path | None = None) -> list[dict]:
    """Load accumulated specs; missing/malformed file or non-spec records
    (no trade_id) yield nothing."""
    path = Path(path) if path is not None else SPEC_FILE
    try:
        existing = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(existing, list):
        return []
    return [sp for sp in existing if isinstance(sp, dict) and "trade_id" in sp]


def merge_specs(existing: list[dict], new: list[dict]) -> list[dict]:
    """Upsert by trade_id: existing records keep their order, new records
    append; a new record with an existing trade_id replaces it in place."""
    new_ids = {sp.get("trade_id") for sp in new}
    kept = [sp for sp in existing if sp.get("trade_id") not in new_ids]
    return kept + new


def save_merged(new: list[dict], path: Path | None = None) -> list[dict]:
    """Merge `new` into the store and write it. Returns the merged list.
    An empty `new` still writes (dropping stale non-spec records) but never
    discards accumulated history."""
    path = Path(path) if path is not None else SPEC_FILE
    merged = merge_specs(load_existing(path), new)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2))
    return merged
