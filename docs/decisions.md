# FlowWolf — Design Decisions

Locked decisions with their rationale. Changing any of these is a refactor:
update this file (and `docs/STATE.md`) in the same change, and do not silently
re-derive behavior.

## Architecture

1. **"Swarm proposes, code disposes."** LLM agents only generate and debate
   ideas. Sizing, fills, P&L attribution, and the gate are pure Python.
   The chair's JSON blocks are the only thing downstream trusts.
2. **Prompts are config, not code.** `swarm/prompts/*.md` loaded via
   `prompts.load(name)`. Editing a prompt never requires a code review.
3. **`run_scan` stays scan-only.** `swarm/crew.py` runs the LLM pipeline and
   persists gated specs; orchestration across scan/fill/mark lives in
   `swarm/daily.py`. This keeps the LLM stage deterministic-cost and
   independently replayable.
4. **`fill_approved` is the single fill loop.** Extracted into
   `swarm/paper.py` and reused by the `paper execute` CLI and `daily.py`.
   Contract: filters specs with `backtest_gate == "approved"` and
   `status != "executed"`, validates via `TradeSpec.model_validate`, stamps
   `status = "executed"` on success, returns `(filled_ids, skipped)`, catches
   per-spec exceptions (one bad fill never aborts the day).
5. **The spec file accumulates; scans never overwrite it.**
   `swarm/specstore.py` owns `data/specs/trade_specs.json`: `save_merged`
   upserts by `trade_id` — new ids append, a re-scan of the same
   date+ticker replaces the older record, an empty-day scan preserves all
   history. Records without a `trade_id` (the chair's empty-day object) are
   dropped on load. `run_scan` merges ungated specs first (a gate crash must
   not lose the LLM spend), then merges the gated versions over the same ids.
   **A gate-approved record is immutable:** a newer record with the same
   `trade_id` is discarded, never replacing it (first approval wins;
   `status: executed` records are approved and therefore protected too).
   Pending/rejected records remain replaceable by re-scans — only approval
   locks the record. Blocked records are reported on stderr by `save_merged`.
6. **Killed ideas are logged and tracked, not discarded.** (Mentor
   feedback: "log the rejected ideas and track them the same way;
   otherwise we can't say the skips were right.") `swarm/rejections.py`
   records every scanned candidate that never became a spec — first fatal
   stage (`dossier_floor` / `skeptic_kill` / `chair`), dossier score and
   verdict, one-line reason — parsed from the mandated stage-B blocks, so
   the log adds no LLM or UW cost. `update_outcomes` marks each record
   with the forward 7-trading-day return from the same historical close
   series the gate uses (point-in-time by construction; pending until the
   bars exist). The log accumulates upsert-by-`rejection_id` and is
   auto-marked by `swarm.daily`.
7. **Close caches never go stale.** A cached 5y close series refreshes
   whenever its newest bar is more than one calendar day old
   (`gate._should_refresh`). Incident: the MU cache written 2026-11-07
   froze three paper fills at the 2026-11-06 close until this rule; the
   fills were re-executed at the true latest close.
   Scout candidate volume is prompt-native (AT MOST 8 in `flow_scout.md`,
   mirrored by `MAX_CANDIDATES=8`); the funnel is deliberately wide —
   `min_premium=100000`, a non-sweep ask-side block pass, and up to 8
   candidates — because killed ideas never become TradeSpecs, so spec volume
   scales with candidate volume.

## Gate (deterministic)

- Approve above `n ≥ 30, win_rate ≥ 0.30, mean_R ≥ 0.05`; hard-reject
  `net ≤ max(0.25 pt, 10% of spread width)` (Phase 7 width-scaled floor;
  replaces the flat 1.0-pt floor, which auto-rejected every budget-capped
  narrow spread) or `risk ≤ 0`. Thresholds chosen so a losing archetype can
  never clear the probabilistic gate.
- **Phase 7 — risk-budget strikes.** Spread width is
  `min(geometric 5%/4% of spot, floor(max_risk_usd × 0.8 / 100))` points,
  minimum 1 pt, threaded through gate and executor: the gate backtests the
  exact structure the paper book can fill, ending the gate-approves /
  executor-refuses mismatch (legacy fixed-% geometry broke the $300 cap for
  any underlying above ~$60). `run_gate` records a `risk_budget` block with
  the width-only budget the legacy geometry would have required at the
  latest close (the mentor's "increase the budget and check" sensitivity).
  Long (single-leg) strategies are unchanged: their premium risk is capped
  by the executor's `max_risk_usd` check.
- Entry IV ≈ 1.15× trailing 20-day realized vol (UW Basic tier has no IV
  endpoints); documented as a v2 upgrade, not a bug.

## Learning loop (`swarm/learn.py`)

Constants: `WIN_RATE_FLOOR = 0.30`, `MEAN_R_FLOOR = 0.05`,
`WIN_RATE_HEALTHY = 0.50`, `MEAN_R_HEALTHY = 0.15`, `CLOSED_MIN = 10`.

- Summary missing/malformed, `closed < 10`, or null metrics → `""` (no
  directive). **Insufficient data never drives the LLM.**
- `win_rate < 0.30` or `mean_r < 0.05` → raise chair minimum confidence to
  8/10, no loosening of exits or quotas.
- `win_rate ≥ 0.50` and `mean_r ≥ 0.15` → healthy: explicitly keep the
  standard 6/10 floor.
- Otherwise → keep the standard 6/10 floor.
- Calibration is deterministic text appended to the chair description;
  the LLM applies it, Python never mutates the prompt content beyond this.

## Executor / tracker

- Defined-risk only, 6 archetypes, 7 DTE, ≤ $300 max risk, cash-settled
  Black–Scholes simulation of the gate; fills at latest close.
- Weekend: `run_scan` refuses to call the LLM; `daily.py` still marks the
  book (the book ages over weekends too).

## Conventions & gotchas (for tests/tools)

- Test framework is **unittest** (pytest is not installed).
- The LLM provider intermittently returns empty completions; crew kickoffs
  retry (`_kickoff`, 3 attempts, fresh `Crew` per attempt, 2s pause) instead
  of aborting a scan. Only `ValueError` containing "None or empty" is
  treated as transient.
- Tests must not import `swarm.crew` (module import spawns the UW MCP
  server process). Spec-store logic lives in `swarm/specstore.py` and is
  imported directly by `tests/test_specstore.py`.
- `reports/raw` and both `ORDERS_DIR` (execute/paper.py and
  execute/tracker.py) must be patched to a tmpdir together; `PNL_DIR` in
  tracker.py must be patched and `.mkdir()`-ed manually.
- `tests/` needs `__init__.py` for discovery.
- `rg` is not installed on this machine; use `grep`.
- `python -m swarm.daily` must be run from the repo root (cwd-relative
  summary path).
- Do not commit without an explicit user request.

## Deferred / explicitly not implemented

- IB paper adapter activation (≥ 30 closed trades precondition).
- bid/ask, theta decay, early exercise in the backtest (documented
  limitation).
- Fixing `paper.SPEC_FILE` vs `crew.SPEC_FILE` styling — see
  `docs/STATE.md` open items; requires doc update alongside.
