"""Real-broker adapter placeholder (IBridgePy + Interactive Brokers paper).

The paper book (swarm.execute.paper) is the current execution authority.
This module documents the integration contract so swapping in IBridgePy is a
drop-in, not a rewrite:

    class IBridgePyAdapter:
        def execute(self, spec: TradeSpec) -> OrderRecord: ...   # place option legs
        def marks(self, records) -> dict: ...                   # live P&L snapshot

Requirements when activating:
- ibridgepy library installed in .venv (commercial license)
- TWS/IB Gateway running with a PAPER account, API enabled
- run_me.py entry (IBridgePy's required harness) adapted to place the same
  leg list stored in data/orders/<trade_id>.json, sized by committed_risk_usd
- fills/positions then update the SAME OrderRecord schema; tracker.py keeps
  working unchanged on live IB fills.

Never enable until the paper book has >= 30 closed trades proving the gate.
"""
from __future__ import annotations

from swarm.models import TradeSpec


class IBridgePyNotInstalled(RuntimeError):
    pass


def execute_real(spec: TradeSpec):
    raise IBridgePyNotInstalled(
        "IBridgePy adapter is not active; the paper book is the execution authority"
    )
