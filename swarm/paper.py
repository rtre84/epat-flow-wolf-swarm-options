"""Paper-book CLI: execute approved specs, mark open positions, print summary.

  ./.venv/bin/python -m swarm.paper execute   # fill every approved, not-yet-executed spec
  ./.venv/bin/python -m swarm.paper mark     # mark-to-market / close expired, print stats

Phase 4 runner. Deterministic; LLM never touches this path.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from swarm.execute.paper import execute_paper
from swarm.execute.tracker import mark_all
from swarm.tools.uw import UWMCPClient

SPEC_FILE = Path("data/specs/trade_specs.json")


def _uw() -> UWMCPClient:
    uw = UWMCPClient()
    uw.initialize()
    return uw


def load_specs() -> list[dict]:
    if not SPEC_FILE.exists():
        return []
    return json.loads(SPEC_FILE.read_text())


def save_specs(specs: list[dict]) -> None:
    SPEC_FILE.write_text(json.dumps(specs, indent=2))


def fill_approved(specs: list[dict], uw: UWMCPClient) -> tuple[list[str], list[dict]]:
    """Fill every approved, not-yet-executed spec in-place (stamps status).

    Returns (filled trade_ids, skipped entries with the failure reason).
    Per-spec failures never abort the remaining fills.
    """
    from swarm.models import TradeSpec
    filled: list[str] = []
    skipped: list[dict] = []
    for sp in specs:
        if sp.get("backtest_gate") != "approved" or sp.get("status") == "executed":
            continue
        spec = TradeSpec.model_validate(sp)
        try:
            rec = execute_paper(spec, uw)
            sp["status"] = "executed"
            filled.append(rec.trade_id)
            print(f"[fill] {rec.trade_id} {rec.strategy} qty={rec.qty} "
                  f"net=${rec.net_usd} risk=${rec.committed_risk_usd}")
        except Exception as e:
            skipped.append({"trade_id": spec.trade_id, "error": str(e)[:200]})
            print(f"[skip] {spec.trade_id}: {e}", file=sys.stderr)
    return filled, skipped


def cmd_execute() -> int:
    specs = load_specs()
    filled, skipped = fill_approved(specs, _uw())
    save_specs(specs)
    print(f"=== EXECUTE: {len(filled)} filled, {len(skipped)} skipped ===")
    return 0


def cmd_mark() -> int:
    uw = _uw()
    summary = mark_all(uw)
    print(json.dumps(summary, indent=2))
    print("=== MARK: done ===")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "execute":
        return cmd_execute()
    if cmd == "mark":
        return cmd_mark()
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
