# FlowWolf — Current State

_Last updated: 2026-11-06. This file is the source of truth for what exists and
how it behaves. Any refactor must update it in the same change._

## Phase status

| Phase | Scope | Commit | Status |
|---|---|---|---|
| 1 | UW MCP client, pydantic models, LLM smoke (`swarm.main`) | `12909b4` | done |
| 2 | Prompts as `.md` config bricks, 3-stage crew, UW tool wrappers | `c93d5a1` / `9a91a67` | done |
| 3 | Backtest gate (archetype simulator) + crew wiring | `f16623c` | done |
| 4 | Paper executor, tracker, IB adapter stub, CLI | `66c1ac6` | done |
| 5 | Daily flow (`swarm/daily.py`) + learning loop (`swarm/learn.py`) | **uncommitted** | code + tests green |

Test suite: `./.venv/bin/python -m unittest discover -s tests` — **21 tests, all green**
(11 pre-existing + 10 in `tests/test_learn.py`).

## Module map (as of Phase 5)

- `swarm/crew.py` — `run_scan(day)`: stage A (regime → scout, one crew), stage B
  per-candidate (dossier → skeptic, capped by `MAX_CANDIDATES=5`), stage C chair
  → JSON specs. Persists every stage transcript to `reports/raw/<date>_<stage>.txt`,
  writes gated specs to `crew.SPEC_FILE` (absolute path under `data/specs/`).
  Returns dict with `candidates`, `n_specs`, `specs`, `empty_day`, `summary`.
  Weekend (`weekday() >= 5`) early-returns without touching files or LLM.
  **Phase 5 change:** chair description now appends `chair_calibration()`
  output when non-empty (`swarm/learn.py`, imported at module top — no cycle).
- `swarm/paper.py` — CLI (`execute`, `mark`). **Phase 5 change:** the fill loop
  was extracted into `fill_approved(specs, uw) -> (filled_ids, skipped_entries)`
  which validates each approved spec via `TradeSpec.model_validate`, stamps
  `sp["status"] = "executed"` on success, and catches per-spec failures so one
  bad fill cannot abort the rest. `cmd_execute` is now a thin wrapper.
  Note: `paper.SPEC_FILE` is cwd-relative (`data/specs/trade_specs.json`),
  identical to `crew.SPEC_FILE` when run from the repo root.
- `swarm/daily.py` — **new.** `run_day(day)` = `run_scan` → read
  `crew.SPEC_FILE` → `fill_approved` on pending approved specs → write specs
  back when filled → `mark_all` if any open order exists → JSON report dict
  (`date`, `weekend`, `scan`, `filled`, `fill_errors`, `book`). CLI:
  `./.venv/bin/python -m swarm.daily [YYYY-MM-DD]`. The `UWMCPClient` is
  created lazily (each instance spawns an MCP server process).
- `swarm/learn.py` — **new.** `chair_calibration(summary_path=None)` reads
  `data/pnl/summary.json` (`SUMMARY_PATH`, cwd-relative). Pure/deterministic,
  no LLM. Rules in `docs/decisions.md`.
- `swarm/execute/paper.py` — `execute_paper`, `MULTIPLIER=100`,
  `MIN_CONTRACT_RISK_USD=25`, writes `data/orders/*.json`.
- `swarm/execute/tracker.py` — `mark_all(uw)` re-marks open records using the
  gate's close logic, closes on stop/expiry, writes `data/pnl/summary.json`
  with keys `tracked, open, closed, realized_pnl_usd, open_committed_risk_usd,
  win_rate, mean_r, records` (`win_rate`/`mean_r` are `None` until ≥ 1 closed).
- `swarm/execute/ib_adapter.py` — IB paper bridge, **disabled** until ≥ 30
  closed trades.
- `swarm/backtest/gate.py` — `gate_spec` (line ~288): approve only above
  `n ≥ 30, win_rate ≥ 0.30, mean_R ≥ 0.05`; hard-reject `net ≤ 1.0 pt` or
  `risk ≤ 0`. Entry IV ≈ 1.15× trailing 20-day realized vol; fixed stops
  (2× premium credits, near-zero debits), otherwise hold to expiry.
- `swarm/prompts/` — `chair.md`, `regime_analyst.md`, `flow_scout.md`,
  `dossier_analyst.md`, `skeptic.md` loaded via `prompts.load(name)`
  (`resources.files("swarm.prompts")`).

## Data artifacts

| Path | Contents |
|---|---|
| `data/specs/trade_specs.json` | gated ideas (`backtest_gate`: `approved` / `pending_backtest` / reject, plus `status`) |
| `data/orders/*.json` | paper fill records |
| `data/pnl/summary.json` | tracker summary (learning-loop input) |
| `data/backtests/cache/` | 5y close series per ticker |
| `reports/raw/` | per-stage agent transcripts |

## Known open items

1. **Not yet verified live:** the chair actually stamping
   `backtest_gate: "approved"` (lowercase string) + `status` fields end-to-end
   through a real LLM scan. Safe to leaves as-is: fills are paper-only and
   per-spec errors are caught.
2. **Path inconsistency:** `paper.SPEC_FILE` (cwd-relative) vs
   `crew.SPEC_FILE` (absolute). `docker`-free daily flow uses `crew.SPEC_FILE`.
   Do not "fix" this in passing — any unification is a refactor demanding a
   doc update first.
3. `reports/parse_warnings.log` is touched but never filled with content.

## Next planned work (do not start before documenting)

- First real `swarm.daily` run (costs LLM + UW calls; run on a weekday).
- IB adapter activation policy after ≥ 30 closed trades.
- README roadmap remainder: UW per-ticker IV, executable entry triggers.
