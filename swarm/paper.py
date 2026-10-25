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


def cmd_execute() -> int:
    specs = load_specs()
    uw = _uw()
    done, errors = 0, 0
    for sp in specs:
        if sp.get("backtest_gate") != "approved" or sp.get("status") == "executed":
            continue
        from swarm.models import TradeSpec
        spec = TradeSpec.model_validate(sp)
        try:
            rec = execute_paper(spec, uw)
            sp["status"] = "executed"
            done += 1
            print(f"[fill] {rec.trade_id} {rec.strategy} qty={rec.qty} "
                  f"net=${rec.net_usd} risk=${rec.committed_risk_usd}")
        except Exception as e:
            errors += 1
            print(f"[skip] {spec.trade_id}: {e}", file=sys.stderr)
    save_specs(specs)
    print(f"=== EXECUTE: {done} filled, {errors} skipped ===")
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
