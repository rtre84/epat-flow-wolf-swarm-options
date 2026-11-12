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
   Scout candidate volume is prompt-native (AT MOST 8 in `flow_scout.md`,
   mirrored by `MAX_CANDIDATES=8`); the funnel is deliberately wide —
   `min_premium=100000`, a non-sweep ask-side block pass, and up to 8
   candidates — because killed ideas never become TradeSpecs, so spec volume
   scales with candidate volume.

## Gate (deterministic)

- Approve above `n ≥ 30, win_rate ≥ 0.30, mean_R ≥ 0.05`; hard-reject
  `net ≤ 1.0 pt` or `risk ≤ 0`. Thresholds chosen so a losing archetype can
  never clear the probabilistic gate.
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
