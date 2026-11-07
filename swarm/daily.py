"""One-command daily flow: scan → gate → fill → mark.

  ./.venv/bin/python -m swarm.daily              # run for today
  ./.venv/bin/python -m swarm.daily 2026-11-05   # run for a specific weekday

On weekends the scan is skipped but the paper book is still marked.
run_scan() persists gated specs; this module deep-fills only approved and
not-yet-executed specs, then marks the book and prints a JSON report.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from swarm import crew
from swarm.execute.paper import ORDERS_DIR
from swarm.execute.tracker import mark_all
from swarm.paper import fill_approved
from swarm.tools.uw import UWMCPClient


def _read_specs() -> list[dict]:
    if not crew.SPEC_FILE.exists():
        return []
    return json.loads(crew.SPEC_FILE.read_text())


def _write_specs(specs: list[dict]) -> None:
    crew.SPEC_FILE.parent.mkdir(parents=True, exist_ok=True)
    crew.SPEC_FILE.write_text(json.dumps(specs, indent=2))


def _has_open_orders() -> bool:
    for path in ORDERS_DIR.glob("*.json"):
        try:
            if json.loads(path.read_text()).get("status") == "open":
                return True
        except (OSError, json.JSONDecodeError):
            continue
    return False


def run_day(day: date | None = None) -> dict:
    day = day or date.today()
    weekend = day.weekday() >= 5
    scan = crew.run_scan(day)

    uw: UWMCPClient | None = None

    def _uw() -> UWMCPClient:
        nonlocal uw
        if uw is None:
            uw = UWMCPClient()
            uw.initialize()
        return uw

    specs, filled, skip_errors = _read_specs(), [], []
    if not weekend:
        pending = [sp for sp in specs
                   if sp.get("backtest_gate") == "approved" and sp.get("status") != "executed"]
        if pending:
            filled, skip_errors = fill_approved(specs, _uw())
            if filled:
                _write_specs(specs)

    marked: dict | None = None
    if _has_open_orders():
        marked = mark_all(_uw())

    return {
        "date": day.isoformat(),
        "weekend": weekend,
        "scan": {k: scan.get(k) for k in ("candidates", "n_specs", "empty_day", "summary")},
        "filled": filled,
        "fill_errors": skip_errors,
        "book": None if marked is None else {k: marked.get(k) for k in
                                             ("open", "closed", "realized_pnl_usd",
                                              "win_rate", "mean_r")},
    }


def main(argv: list[str]) -> int:
    day = None
    if argv:
        try:
            day = date.fromisoformat(argv[0])
        except ValueError:
            print(f"bad date (use YYYY-MM-DD): {argv[0]}", file=sys.stderr)
            return 2
    print(json.dumps(run_day(day), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
