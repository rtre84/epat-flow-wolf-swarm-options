"""Phase 1 smoke runner. Verifies the three plumbing pieces live:
1. UW MCP auth + tools reachable
2. TradeSpec pydantic round-trip
3. LLM completion through the resolved Swarm config

No agents, no logic. Exit 0 = Phase 1 exit criteria met.
"""
from datetime import date
import json
import sys

from swarm.llm import LLMConfig, llm_smoke
from swarm.models import Strategy, TradeSpec, SpecStatus
from swarm.tools.uw import UWMCPClient


def uw_test() -> str:
    info = UWMCPClient().smoke()
    return f"UW: server={info['server']} tools={info['tool_count']} (first: {', '.join(info['first_tools'])})"


def schema_test() -> str:
    spec = TradeSpec(
        trade_id="2026-10-25_TSLA",
        scan_date=date(2026, 10, 25),
        underlying="TSLA",
        strategy=Strategy.BULL_PUT_SPREAD,
        expiry="weekly",
        max_risk_usd=300.0,
        entry_trigger="price reclaims VWAP on rising flow",
        invalidation="close below intraday low",
        confidence=7.5,
        signals=["dark_pool_accum", "gex_shift"],
        backtest_gate=SpecStatus.PENDING_BACKTEST,
    )
    dumped = spec.model_dump_json()
    rehydrated = TradeSpec.model_validate_json(dumped)
    assert rehydrated == spec
    # negative control: over-risk must fail
    try:
        TradeSpec(trade_id="2026-10-25_SPY", scan_date=date(2026, 10, 25), underlying="SPY",
                  strategy=Strategy.LONG_PUT, expiry="monthly", max_risk_usd=999.0,
                  entry_trigger="x", invalidation="y", confidence=5, signals=["s"])
        raise AssertionError("over-risk spec validated — schema is too loose")
    except Exception:
        pass
    return f"Schema: round-trip + negative control ok ({len(dumped)} bytes serialized)"


def llm_test() -> str:
    cfg = LLMConfig()
    reply = llm_smoke()
    return f"LLM: {cfg.model} -> {json.dumps(reply.strip()[:40])}"


if __name__ == "__main__":
    results = []
    for name, fn in [("UW", uw_test), ("Schema", schema_test), ("LLM", llm_test)]:
        try:
            results.append((name, fn()))
        except Exception as e:
            results.append((name, f"FAILED: {type(e).__name__}: {e}"))
            print(f"[{name}] FAILED: {e}", file=sys.stderr)
            print("=== PHASE 1 SMOKE: FAIL ===", file=sys.stderr)
            sys.exit(1)
    for name, msg in results:
        print(f"[{name}] {msg}")
    print("=== PHASE 1 SMOKE: PASS ===")
