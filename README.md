# FlowWolf

A multi-agent LLM swarm that mines, validates, and paper-trades options ideas from Unusual Whales market-flow data.

**Architecture thesis:** *The swarm proposes; code disposes.* LLM agents (CrewAI) generate and debate trade ideas from market-flow context, but every idea is rewritten into a strict, schema-validated `TradeSpec`, backtested by a deterministic Black–Scholes archetype simulator, and only filled on a paper book if it clears statistical gate thresholds. LLMs never touch sizing, fills, or P&L attribution.

## Pipeline

```
UW MCP data
   │
   ▼
┌─ Stage A ─ regime analyst → flow scout ──────────────→ 5 tickers max
├─ Stage B ─ per-ticker dossier → skeptic (antagonist) ─→ surviving ideas
├─ Stage C ─ chair → TradeSpec JSON (pydantic-validated) → data/specs/trade_specs.json
│
├─ BACKTEST GATE (deterministic) ─ 5y closes + Black–Scholes legs
│            approved only if: n ≥ 30, win_rate ≥ 0.30, mean_R ≥ 0.05
│
├─ EXECUTOR (deterministic) ── paper fills → data/orders/*.json
├─ TRACKER ─────────────────── mark-to-market → data/pnl/summary.json
└─ LEARN ───────────────────── paper P&L recalibrates chair prompts
```

## Docs

- [`docs/STATE.md`](docs/STATE.md) — current state: phase commits, module behavior, data artifacts, open items
- [`docs/decisions.md`](docs/decisions.md) — locked design decisions, thresholds, and testing gotchas

## Strategies

Defined-risk only — 6 archetypes, 7-DTE weekly expiration, ≤ $300 max risk:

| Strategy | Type | Profile |
|---|---|---|
| `long_call` | debit | strongly bullish |
| `long_put` | debit | strongly bearish |
| `bull_call_spread` | debit | bullish |
| `bear_put_spread` | debit | bearish |
| `bull_put_spread` | credit | moderately bullish |
| `bear_call_spread` | credit | moderately bearish |

## Layout

```
swarm/
  main.py            # Phase 1 smoke checks (UW / schema / LLM)
  llm.py             # OpenAI-compatible client (SWARM_MODEL)
  models.py          # TradeSpec, SpecStatus pydantic models
  crew.py            # run_scan(): 3-stage CrewAI orchestration
  daily.py           # one-command day: run_scan → fill approved → mark book
  learn.py           # chair_calibration(): P&L facts → chair prompt directive
  prompts/             # all agent prompts as .md files (config, not code)
  tools/
    uw.py              # UW MCP client (rate-disciplined)
    uw_tools.py        # typed CrewAI tools over UW endpoints
  backtest/
    gate.py          # CloseSeries, Black–Scholes legs, archetype simulator, gate
  execute/
    paper.py         # fill engine → data/orders/
    tracker.py       # mark-to-market → data/pnl/summary.json
    ib_adapter.py    # IB paper account bridge (staged, inactive)
  paper.py           # CLI: execute approved specs / mark the book
tests/               # unittest suite (gate + executor + tracker)
reports/raw/         # per-stage agent transcripts (auditable)
data/                # specs, orders, pnl summary, price cache
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # crewai, pydantic, openai, httpx, etc.

cp .env.example .env              # then fill in:
#   UWMCP_*      Unusual Whales MCP server config
#   SWARM_MODEL  e.g. openai/<model-id> (any OpenAI-compatible endpoint)
#   OPENAI_* / provider keys
```

> **Required:** Unusual Whales API access (MCP server), and any OpenAI-compatible LLM endpoint. Secrets live in `.env` — never commit it.

## Usage

```bash
# Verify connectivity + schema + LLM round-trip
./.venv/bin/python -m swarm.main

# Full scan: agents propose → gate backtests → writes data/specs/trade_specs.json
./.venv/bin/python -m swarm.crew

# Daily flow (one command): scan → fill approved specs → mark the book → JSON report
# (weekends skip the scan but still mark open paper positions)
./.venv/bin/python -m swarm.daily
./.venv/bin/python -m swarm.daily 2026-11-05   # explicit date

# Fill only gate-approved, not-yet-executed specs (paper book)
./.venv/bin/python -m swarm.paper execute

# Mark the book daily: closes stopped/expired positions, writes summary
./.venv/bin/python -m swarm.paper mark

# Run tests
./.venv/bin/python -m unittest discover -s tests -v
```

## Gate math (v1)

- Entry IV ≈ 1.15 × trailing 20-day realized vol (`realized_vol_20`)
- Price legs vectorized Black–Scholes; strikes from spot geometry
  (e.g. bull put spread: short 0.96×spot, long 0.91×spot)
- Simulate every eligible historical entry (5-day stepping), fixed stops
  (2× premium for credits, near-zero for debits), hold to expiry otherwise
- Approve only above `n ≥ 30`, `win_rate ≥ 0.30`, `mean_R ≥ 0.05`;
  hard-reject `net ≤ 1.0 pt` or `risk ≤ 0`

## Limitations (honest)

- UW Basic tier: no SMA/RSI endpoints — computed locally; ~40 calls/scan budget
- IV model ignores vol risk premium/skew; directional, not tradable-grade
- Entry triggers are advisory; fills happen at latest close
- No bid/ask spread, theta decay, or early-exercise modeling in the backtest
- IB adapter is coded but **disabled** until the paper book has ≥ 30 closed trades

## Roadmap (v2)

- Use UW per-ticker IV fields instead of the 1.15× realized-vol proxy
- Make entry triggers executable in the paper book (e.g. VWAP reclaim guards)
- Activate the Interactive Brokers paper adapter once the book records ≥ 30 closed trades
- ~~Wire the learning loop end-to-end~~ — shipped: after each mark, `swarm.learn.chair_calibration()` reads `data/pnl/summary.json` and appends a directive to the chair prompt (raise to 8/10 confidence when win_rate < 0.30 or mean_R < 0.05 with ≥ 10 closed trades)

## Data artifacts

| Path | Contents |
|---|---|
| `data/specs/trade_specs.json` | generated ideas + gate verdicts |
| `data/orders/` | paper fill records |
| `data/pnl/summary.json` | realized P&L, win rate, mean R |
| `data/backtests/cache/` | 5y close series per ticker |
| `reports/raw/` | agent transcripts per stage |
