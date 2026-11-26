# Point-in-Time Data Audit

_Mentor requirement: backdated scans must not read today's snapshot —
every endpoint returns data as of the scan day, or the run carries look-ahead
bias and is excluded from performance claims._

Audit method: the UW MCP server's `tools/list` input schemas were probed
live (139 tools enumerated; the 10 wrapped endpoints inspected parameter by
parameter) on 2026-11-26. Verdicts below are ground truth from the server,
not documentation inference.

## Endpoint verdicts (as wrapped by `swarm/tools/uw_tools.py`)

| Tool | Date support in UW API | Wrapper exposes it? | Point-in-time? |
|---|---|---|---|
| `get_market_tide` | `date` | yes | **yes** |
| `get_flow_alerts` | `newer_than` / `older_than` | yes (Phase 9; was silently dropped) | **yes** |
| `get_dark_pool_trades` | `newer_than` / `older_than` | yes (Phase 9) | **yes** |
| `get_max_pain` | `date` | yes (Phase 9) | **yes** |
| `get_gex_levels` | `date` | yes (Phase 9) | **yes** |
| `get_recent_congress_trades` | `date` | yes (Phase 9) | **yes** |
| `get_upcoming_earnings` | `min_date` / `max_date` | yes (Phase 9; `min_date` was hardcoded to today) | **yes** |
| `get_market_state` | none (no params) | — | **no — current-only** |
| `get_options_chain` | `expiry` only, no as-of date | — | **no — current-only** |
| `get_insider_activity_by_ticker` | none (ticker only) | — | **no — 30d lookback from today** |

## How as-of calling is enforced

- Every agent's task description carries the point-in-time discipline
  (`crew.TOOL_HINT`): pass the scan date to every dated tool
  (`date` / `date_param` / `newer_than` / `older_than` / `min_date`),
  and treat the three current-only tools as such.
- `get_upcoming_earnings` derives its window from `min_date` (+10 days),
  no longer from the wall clock.
- Wrapper argument forwarding is unit-tested (`tests/test_uw_tools.py`).

## Locked policy

1. **Performance claims come only from live-date scans** (scan date =
   the trading day the data describes). The paper book, rejection outcomes,
   and the learning loop consume live scans.
2. **The 2026-11-02 → 11-07 backfill scans are marked look-ahead-biased**
   and excluded from performance claims: they ran on one sitting-day's
   snapshot regardless of the stamped date. The two specs they produced
   (`2026-11-03_MU`, `2026-11-06_MU`) remain in the store as approved
   (immutable by the Phase 6.3 decision) but their evidence is
   contemporaneous-with-Nov-7, not as-of their stamped dates.
3. Backdated scans remain permitted for **volume/diagnostic purposes** but,
   post-Phase 9, seven of ten data legs are as-of correct; the three
   current-only tools (`market_state`, `options_chain`, `insider`) are
   unavoidable look-ahead legs and are declared in every such run.
4. The gate's backtests are point-in-time by construction (historical
   close series, entry stepped 5 trading days); the close cache refreshes
   when older than one trading day (Phase 8), so fills and marks never
   use a stale last bar.
