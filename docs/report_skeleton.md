# FlowWolf — EPAT Final Report: Working Skeleton

_Status: draft skeleton. Sections 1–5 are ~80% written from existing
artifacts; `FILL` markers show where the paper book's realized numbers land
after the Dec 4 expiries. This file is the compilation checklist for the
final report (`FlowWolf_EPAT_Report.docx`)._

---

## 1. Objective & Architecture

**Thesis:** *"The swarm proposes; code disposes."* LLM agents generate and
debate trade ideas from Unusual Whales market-flow data, but every idea is
rewritten into a schema-validated `TradeSpec`, backtested by a deterministic
Black–Scholes archetype simulator, and only filled on a paper book if it
clears statistical gate thresholds. LLMs never touch sizing, fills, or P&L.

**Pipeline** (copy from `README.md`): UW MCP data → Stage A (regime →
scout, ≤8 candidates) → Stage B (per-ticker dossier → skeptic) → Stage C
(chair → `TradeSpec` JSON) → BACKTEST GATE (deterministic) → EXECUTOR
(paper fills) → TRACKER (mark-to-market) → LEARN (P&L recalibrates the
chair prompt).

**Build history:** phase table from `docs/STATE.md` (Phases 1–10, each
with its commit hash: `12909b4` → `1dc1608`, 95/95 tests green).

## 2. Evidence Chain (every claim → artifact)

| Claim | Artifact |
|---|---|
| Ideas are schema-valid and accumulate without loss | `data/specs/trade_specs.json` (4 approved specs, upsert-by-trade_id, approved records immutable) |
| Every approved spec was backtested over 5y of closes with budget-capped strikes | `data/backtests/*.json` gate audits incl. `risk_budget` sensitivity blocks |
| Approved specs actually filled inside the $300 cap | `data/orders/*.json` (4 fills: 3× MU @ 601.25, 1× SMTC @ 92.93) |
| Positions marked / closed with realized P&L | `data/orders/*.json` status fields + `data/pnl/summary.json` — **FILL: closed-trade stats after Dec 4** |
| Killed ideas were logged and judged | `data/rejections/rejections.json` (38 records, 27 with forward 7d outcomes) |
| Backtests used real historical quotes | `data/study/baseline_4y.{json,md}` + raw dumps |
| No look-ahead bias in live-scan claims | `docs/pit_audit.md` |

## 3. Baseline Study: the mechanical rule has no edge

(From `data/study/baseline_4y.md` + `decisions.md` #9.)

- Setup: ATM call+put volume z-score ≥ 2 (trailing 20d) = flow day; replay
  the pipeline's own entry rule (budget-capped bull put spread, real
  Polygon EOD closes, 7+ day expiry, expiry settle) on flow vs ordinary
  days. 2022–2026, 5 tickers, split-adjusted starts for NVDA/TSLA.
- Result: **79 flow vs 1,111 ordinary entries; pooled edge +0.001 R (null).**
  Per-ticker: TSLA +0.190, NVDA +0.144, QQQ −0.275, MU −0.318 (flow
  samples 8–27 each — present but not statistically decisive).
- Interpretation: raw "unusual volume" carries no dependable edge. Any
  FlowWolf value must come from the qualitative filtering layers —
  which is exactly what the rejection log tests (§4).
- Coverage note: qualifying entries concentrate in the later window —
  the study applies the live gate's own credit floor, which skips
  low-vol index-ETF years (4% OTM 7d spreads earning < 0.25 pt).

## 4. Rejection Log: the filtering layers demonstrably work

(From `data/rejections/rejections.json`.)

- Every killed candidate recorded with stage, score, reason; forward
  7-trading-day outcomes marked from historical closes (point-in-time).
- **Vindicated:** every NVDA kill preceded −14% to −28% forward moves
  (pre-earnings-crash, scores 1–3, killed at dossier/skeptic stage across
  5 scan dates).
- **Honest miss:** AVGO killed at score 5 (+16.3% forward) — sub-floor,
  logged as wrong.
- Framing: the swarm's selectivity is its only candidate source of edge
  (§3 shows the mechanical signal alone adds nothing).

## 5. Methodological Rigor (what we fixed and how we know)

- **Risk-budget strikes** (mentor item A): width =
  `min(% geometry, floor(cap×0.8/100))` pts; gate backtests the exact
  fillable structure; executor shares the function. Proven: fills went
  from impossible ($2,113/contract) to routine ($195–$223 committed).
- **Point-in-time discipline** (item C): UW schema audit, date params
  exposed on all dated endpoints, scan-date instruction in every task;
  locked policy: performance claims only from live-date scans; the
  Nov 2–7 backfill runs marked look-ahead-biased and excluded.
- **Close-cache self-refresh** (found incident): a stale cache had
  frozen the first fills at a 19-day-old close; orders re-executed at
  the true close; regression-tested (`_should_refresh`).
- **Reliability:** kickoff retries on provider empty responses (three
  crashes → zero since); transport-level retries in the study client.

## 6. Live Results — FILL after Dec 4

- Positions: 3× MU bull put spreads (entry 2026-11-25 @ 601.25,
  committed $206.01 each) + 1× SMTC (entry @ 92.93, committed $194.61);
  7 DTE, expiry 2026-12-04.
- **FILL:** realized P&L per position, win rate, mean R
  (`data/pnl/summary.json` after the Dec 4+ mark runs).
- **FILL:** learning-loop status — by design it stays passive under 10
  closed trades; state that explicitly with the rule
  ("insufficient data never drives the LLM").
- **FILL:** comparison line vs the baseline (§3) — the live book's
  realized stats next to the mechanical rule's ordinary-day stats.

## 7. Limitations & Next Steps

- Gate IV is a proxy (1.15× trailing realized vol; UW Basic has no IV
  endpoints) — directional-grade, not tradable-grade. No bid/ask,
  theta, or early exercise in the simulator.
- Study settles at expiry only (live book also stops at 2× premium);
  real-grid constraint: $5-grid names cannot fund $300 spreads at all —
  entries concentrate on $1/$2.5-grid names.
- Three UW endpoints have no historical mode (declared in
  `docs/pit_audit.md`).
- Next steps: UW per-ticker IV upgrade; executable entry triggers
  (VWAP-reclaim guards); holiday calendar for the scan guard; IB paper
  adapter activation after ≥ 30 closed trades.

---

### Compilation checklist (final week)

- [ ] Run `swarm.paper mark` after Dec 4; paste §6 numbers
- [ ] Pull per-position outcomes from `data/orders/*.json`
- [ ] Update the docx from this skeleton; keep the two tables intact
- [ ] One-paragraph abstract from §3 + §4 (the null baseline + the
      working filters is the honest headline)
