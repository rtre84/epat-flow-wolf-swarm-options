# FlowWolf — Current State

_Last updated: 2026-11-07. This file is the source of truth for what exists and
how it behaves. Any refactor must update it in the same change._

## Phase status

| Phase | Scope | Commit | Status |
|---|---|---|---|
| 1 | UW MCP client, pydantic models, LLM smoke (`swarm.main`) | `12909b4` | done |
| 2 | Prompts as `.md` config bricks, 3-stage crew, UW tool wrappers | `c93d5a1` / `9a91a67` | done |
| 3 | Backtest gate (archetype simulator) + crew wiring | `f16623c` | done |
| 4 | Paper executor, tracker, IB adapter stub, CLI | `66c1ac6` | done |
| 5 | Daily flow (`swarm/daily.py`) + learning loop (`swarm/learn.py`) | `f1d0a23` | done |
| 6 | Spec store (accumulate by `trade_id`), scout cap → prompt-native 5, scan CLI | `6db770d` | done |
| 6.1 | Funnel widening: 8 candidates, $100k premium floor, non-sweep block pass | `576a41c` | done |
| 6.2 | Kickoff retry on empty LLM responses; scout `expected_output` cap fix | `a82407f` | done |
| 6.3 | Approved-spec immutability in the spec store | `21b2f58` | done |
| 7 | Risk-budget strikes (mentor feedback): width capped to `max_risk_usd`, width-scaled net floor, budget sensitivity in gate reports | `44a4765` | done |
| 8 | Rejection log (mentor: track the skips) + close-cache refresh fix (stale-cache fill bug) | `711f5dd` | done |
| 9 | Point-in-time fixes (mentor: no look-ahead bias): date params exposed on all dated UW wrappers, scan-date discipline in every task, `docs/pit_audit.md` + locked policy | `980b143` | done |
| 10 | Baseline study (mentor: external backtester): Polygon real historical option quotes, mechanical flow rule, flow days vs ordinary days | `c3602bd` | code + tests green; pilot run complete |

Test suite: `./.venv/bin/python -m unittest discover -s tests` — **93 tests, all green**
(21 pre-existing + 20 specstore + 15 gate Phase 7/8 + 11 rejections +
10 uw_tools + 16 study tests, with `test_paper.py` updated to the
Phase 7 fill semantics).

## Module map (as of Phase 6)

- `swarm/specstore.py` — **new (Phase 6).** Owns `data/specs/trade_specs.json`
  as an accumulating store: `save_merged(new)` upserts by `trade_id` (new ids
  append; a re-scan of the same date+ticker replaces the older record; an
  empty scan never discards history). Records without `trade_id` (e.g. the
  chair's empty-day object) are dropped on load. **Phase 6.3:** a stored
  record with `backtest_gate == "approved"` is immutable — a newer same-id
  record is discarded (first approval wins; duplicate ids within a batch
  keep the first; pending/rejected records stay replaceable; blockers are
  reported on stderr). Import-light on purpose:
  tests must not import `swarm.crew` (it spawns the UW MCP server at import).
- `swarm/rejections.py` — **new (Phase 8).** Rejection log: every scanned
  candidate that does NOT become a spec is recorded (`rejection_id` =
  date_ticker) with the first fatal stage (`dossier_floor` / `skeptic_kill`
  / `chair`), dossier score, verdict, and reasoning — parsed from the
  mandated DOSSIER/SKEPTIC blocks stage B already produces (no extra LLM/UW
  cost). `update_outcomes(uw)` fills the forward 7-trading-day return from
  the gate's close series (point-in-time by construction). Accumulates
  upsert-by-id like the spec store; wired into `run_scan` (records) and
  `swarm.daily` (auto-marks outcomes; report key `rejections_marked`).
  CLI: `python -m swarm.rejections list | mark | backfill` — the
  transcript backfill reconstructed 38 records across 9 scan dates,
  27 with outcomes.
- `swarm/crew.py` — `run_scan(day)`: stage A (regime → scout, one crew), stage B
  per-candidate (dossier → skeptic, capped by `MAX_CANDIDATES=8`), stage C chair
  → JSON specs. Persists every stage transcript to `reports/raw/<date>_<stage>.txt`,
  persists gated specs via `specstore.save_merged` (ungated merge first so a
  gate crash cannot lose the scan, then the gated merge replaces the same
  `trade_id`s). Returns dict with `candidates`, `n_specs`, `specs`,
  `empty_day`, `summary`. Weekend (`weekday() >= 5`) early-returns without
  touching files or LLM. Chair description appends `chair_calibration()`
  output when non-empty (`swarm/learn.py`, imported at module top — no cycle).
  **Phase 6 changes:** the in-code "keep it to 3 candidates" scout cap is
  removed — the prompt's candidate cap governs (AT MOST 8 since Phase 6.1:
  `min_premium=100000` + a non-sweep ask-side block pass in `flow_scout.md`,
  `MAX_CANDIDATES=8` in code, AT MOST 8 specs in `chair.md`);
  **Phase 6.2:** every crew kickoff goes through `_kickoff(build)` which
  retries up to `KICKOFF_ATTEMPTS=3` times on the provider's transient
  empty completions (`ValueError: Invalid response from LLM call - None or
  empty.`), building a fresh `Crew` per attempt; the scout task's
  `expected_output` no longer says "at most 3 ranked candidates" (a
  leftover from the original 3-cap that silently pinned every scan to
  3 candidates); `SPEC_FILE` is now a re-export of
  `specstore.SPEC_FILE` (same absolute path; `daily.py` reads `crew.SPEC_FILE`);
  scan-only CLI `main(argv)` accepts an optional `YYYY-MM-DD` date
  (`python -m swarm.crew [date]`) and prints `total_specs` (accumulated count).
- `swarm/paper.py` — CLI (`execute`, `mark`). **Phase 5 change:** the fill loop
  was extracted into `fill_approved(specs, uw) -> (filled_ids, skipped_entries)`
  which validates each approved spec via `TradeSpec.model_validate`, stamps
  `sp["status"] = "executed"` on success, and catches per-spec failures so one
  bad fill cannot abort the rest. `cmd_execute` is now a thin wrapper.
  Note: `paper.SPEC_FILE` is cwd-relative (`data/specs/trade_specs.json`),
  identical to `crew.SPEC_FILE` when run from the repo root.
- `swarm/daily.py` — `run_day(day)` = `run_scan` → read
  `crew.SPEC_FILE` → `fill_approved` on pending approved specs → write specs
  back when filled → `mark_all` if any open order exists → JSON report dict
  (`date`, `weekend`, `scan`, `total_specs`, `filled`, `fill_errors`, `book`;
  `total_specs` is the accumulated spec count after the scan). CLI:
  `./.venv/bin/python -m swarm.daily [YYYY-MM-DD]`. The `UWMCPClient` is
  created lazily (each instance spawns an MCP server process).
- `swarm/learn.py` — **new.** `chair_calibration(summary_path=None)` reads
  `data/pnl/summary.json` (`SUMMARY_PATH`, cwd-relative). Pure/deterministic,
  no LLM. Rules in `docs/decisions.md`.
- `swarm/execute/paper.py` — `execute_paper`, `MULTIPLIER=100`,
  `MIN_CONTRACT_RISK_USD=25`, writes `data/orders/*.json`. **Phase 7:**
  strikes come from `_pick_strikes(..., spec.max_risk_usd)` — identical
  budget-capped geometry as the gate's simulation — and the degenerate-net
  floor is the gate's width-scaled default (no local override), so a
  gate-approved structure always funds inside the spec's cap.
- `swarm/execute/tracker.py` — `mark_all(uw)` re-marks open records using the
  gate's close logic, closes on stop/expiry, writes `data/pnl/summary.json`
  with keys `tracked, open, closed, realized_pnl_usd, open_committed_risk_usd,
  win_rate, mean_r, records` (`win_rate`/`mean_r` are `None` until ≥ 1 closed).
- `swarm/execute/ib_adapter.py` — IB paper bridge, **disabled** until ≥ 30
  closed trades.
- `swarm/backtest/gate.py` — `gate_spec`: approve only above
  `n ≥ 30, win_rate ≥ 0.30, mean_R ≥ 0.05`; hard-reject
  `net ≤ max(0.25 pt, 10% of width)` or `risk ≤ 0`. Entry IV ≈ 1.15×
  trailing 20-day realized vol; fixed stops (2× premium credits,
  near-zero debits), otherwise hold to expiry. **Phase 7:** strikes are
  risk-budget-aware — `_pick_strikes(spot, direction, dte, max_risk_usd)`
  sizes width `min(geometric, floor(cap×0.8/100))` pts, min 1 pt;
  `gate_spec` threads the spec's `max_risk_usd` through `run_gate →
  evaluate → simulate_archetype` so the backtest simulates the exact
  fillable structure; `run_gate` adds a `risk_budget` block (cap, width
  rule, legacy-geometry budget at latest close) when a budget is given.
  `max_risk_usd=None` keeps the legacy geometry. **Phase 8:** the close
  cache refreshes when its newest bar is more than one calendar day old
  (`_should_refresh`) — the MU cache written 2026-11-07 had silently
  frozen fills and marks at the 11-06 close; the three corrupt MU fills
  were re-executed at the true 11-25 close after the fix.
- `swarm/prompts/` — `chair.md`, `regime_analyst.md`, `flow_scout.md`,
  `dossier_analyst.md`, `skeptic.md` loaded via `prompts.load(name)`
  (`resources.files("swarm.prompts")`).
- `swarm/study/` — **new (Phase 10).** The baseline study (mentor
  requirement: an external backtester using real historical option quotes
  that accepts our own signal dates, comparing flow days against ordinary
  days over years of history):
  - `client.py` — Polygon/Massive REST client, key via `.env`
    (`POLYGON_API_KEY`), every response cached under
    `data/study/cache/` (resumable pulls), retries on 429/5xx and
    transport drops. Historical aggregates only — point-in-time by
    construction.
  - `contracts.py` — pure strike-grid helpers ($1 grid on index ETFs and
    sub-$200 names, $2.5/$5 above), Friday expiry selection, Polygon
    `O:SYMYYMMDD[C/P]NNNNNNNN` tickers.
  - `flow_rule.py` — mechanical flow signal: ATM call+put volume z-score
    vs the trailing 20 days (window excludes the scored day); volume only,
    no OI (historical OI needs a higher tier).
  - `replay.py` — the live pipeline's entry rule on real EOD closes
    (short 0.96×spot put spread on the real grid, width capped to the
    $300 budget, 7+ day expiry, expiry settle). Skips quotes-missing,
    degenerate, and unfundable structures — the gate's filters plus the
    executor's cap. Honest finding: high-priced names on $5 grids cannot
    fund a $300 spread at all (real chains list no narrower strikes);
    entries concentrate on $1/$2.5-grid names.
  - `report.py` — flow vs ordinary buckets (n, win rate, mean R, median R)
    → `data/study/baseline.{json,md}`.
  - CLI: `python -m swarm.study run --tickers SPY,QQQ,NVDA,TSLA,MU
    --start 2025-11-01 [--z 2.0] [--stride 1]`.
- `swarm/tools/uw.py` — minimal streamable-HTTP MCP client (no SDK).
- `swarm/tools/uw_tools.py` — typed CrewAI tools over UW endpoints
  (rate-disciplined, one lazily-initialized shared client — import spawns
  no MCP session since Phase 9). **Phase 9 (point-in-time):** all dated
  endpoints accept the scan date (`date_param` / `newer_than` /
  `older_than` / `min_date`); `get_upcoming_earnings` windows from
  `min_date`, not the wall clock; `get_market_state`,
  `get_options_chain`, and `get_insider_activity_by_ticker` are
  current-only (no historical mode in the UW API — see
  `docs/pit_audit.md`). Argument forwarding is unit-tested
  (`tests/test_uw_tools.py`), and `crew.TOOL_HINT` carries the
  scan-date discipline to every agent task.

## Data artifacts

| Path | Contents |
|---|---|
| `data/specs/trade_specs.json` | accumulated gated ideas, upserted by `trade_id` (`backtest_gate`: `approved` / `pending_backtest` / reject, plus `status`); scans never overwrite history |
| `data/orders/*.json` | paper fill records |
| `data/rejections/rejections.json` | every killed candidate: stage, score, reason, forward 7d outcome |
| `data/study/baseline.{json,md}` | flow-days vs ordinary-days baseline (Polygon real quotes) |
| `data/study/cache/` | cached Polygon responses (resumable pulls) |
| `data/pnl/summary.json` | tracker summary (learning-loop input) |
| `data/backtests/cache/` | 5y close series per ticker |
| `reports/raw/` | per-stage agent transcripts |

## Known open items

1. **Not yet verified live:** the chair actually stamping
   `backtest_gate: "approved"` (lowercase string) + `status` fields end-to-end
   through a real LLM scan. Safe to leaves as-is: fills are paper-only and
   per-spec errors are caught.
2. **Path inconsistency:** `paper.SPEC_FILE` (cwd-relative) vs
   `crew.SPEC_FILE` (absolute, now a re-export of `specstore.SPEC_FILE`).
   `docker`-free daily flow uses `crew.SPEC_FILE`.
   Do not "fix" this in passing — any unification is a refactor demanding a
   doc update first.
3. `reports/parse_warnings.log` is touched but never filled with content.

## Next planned work (do not start before documenting)

- First real `swarm.daily` run (costs LLM + UW calls; run on a weekday).
- IB adapter activation policy after ≥ 30 closed trades.
- README roadmap remainder: UW per-ticker IV, executable entry triggers.
