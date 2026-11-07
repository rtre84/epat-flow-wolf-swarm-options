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
