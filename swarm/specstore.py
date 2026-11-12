"""Persistent TradeSpec store: scans accumulate, never overwrite.

`data/specs/trade_specs.json` is upserted by `trade_id` (date_ticker) so
repeated scans build history instead of replacing it: new ids append, a
re-scan of the same date+ticker replaces the older record — unless that
stored record is gate-approved, in which case it is kept and the newer
duplicate discarded (first approval wins). Records without a `trade_id`
(e.g. the chair's empty-day object) are not specs and are dropped on load.

Kept import-light (no crew/UW imports) so tests can use it directly:
importing `swarm.crew` spawns the UW MCP server process.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SPEC_FILE = Path(__file__).resolve().parent.parent / "data" / "specs" / "trade_specs.json"


def _is_approved(spec: dict) -> bool:
    return spec.get("backtest_gate") == "approved"


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
    """Upsert by trade_id, preserving existing order and arrival order.

    - a new id appends; a re-scan of the same id replaces the stored record
      in place — unless the stored record is gate-approved, which is
      immutable: the newer duplicate is discarded.
    - a duplicate trade_id within `new` itself keeps the first occurrence.
    """
    approved_ids = {sp.get("trade_id") for sp in existing
                    if isinstance(sp, dict) and _is_approved(sp)}
    new_by_id: dict[str, dict] = {}
    order: list[str] = []
    tail: list[dict] = []  # new records without a trade_id (tolerated as-is)
    for sp in new:
        tid = sp.get("trade_id") if isinstance(sp, dict) else None
        if tid is None:
            tail.append(sp)
        elif tid not in new_by_id:
            new_by_id[tid] = sp
            order.append(tid)

    out: list[dict] = []
    for sp in existing:
        tid = sp.get("trade_id")
        if tid in new_by_id and tid not in approved_ids:
            continue  # replaced in place by the newer record
        out.append(sp)  # kept: no challenger, or approved → immutable

    kept_ids = {sp.get("trade_id") for sp in out}
    for tid in order:
        if tid not in kept_ids:
            out.append(new_by_id[tid])
    out.extend(tail)
    return out


def save_merged(new: list[dict], path: Path | None = None) -> list[dict]:
    """Merge `new` into the store and write it. Returns the merged list.
    An empty `new` still writes (dropping stale non-spec records) but never
    discards accumulated history. New records blocked by an approved spec
    are reported on stderr."""
    path = Path(path) if path is not None else SPEC_FILE
    existing = load_existing(path)
    merged = merge_specs(existing, new)
    for sp in new:
        if isinstance(sp, dict) and _is_approved(next(
                (e for e in existing if e.get("trade_id") == sp.get("trade_id")), {})):
            print(f"[store] {sp.get('trade_id')}: keeping the gate-approved "
                  f"record; discarding the newer duplicate", file=sys.stderr)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2))
    return merged
