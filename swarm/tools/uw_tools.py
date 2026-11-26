"""CrewAI tool wrappers over the UW MCP client.

Each tool is a thin, JSON-string-in/JSON-string-out projection with a size
cap (agent context windows are precious). Real parameter names verified live
against the server's tools/list. Rate discipline: these serialize through one
client; scans stay well under UW Basic's 120 req/min.

Point-in-time (Phase 9): dated endpoints accept the scan date (date /
newer_than / older_than / min_date). get_market_state, get_options_chain,
and get_insider_activity_by_ticker have no historical mode — they are
current-only and flagged in docs/pit_audit.md.

The client is lazy: importing this module must not spawn an MCP session
(it did before Phase 9, which also made the wrappers untestable).
"""
import json
from datetime import date, timedelta

from crewai.tools import tool

from swarm.tools.uw import UWMCPClient

_client: UWMCPClient | None = None

MAX_CHARS = 6000


def _uw() -> UWMCPClient:
    """Lazy shared client (rate discipline: one session, serialized calls)."""
    global _client
    if _client is None:
        _client = UWMCPClient()
        _client.initialize()
    return _client


def _projects(resp: dict) -> str:
    """MCP tools/call envelope -> text content, capped."""
    content = (resp or {}).get("result", {}).get("content", [])
    parts = [b.get("text", "") for b in content if isinstance(b, dict)]
    text = "\n".join(p for p in parts if p)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n...[truncated at {MAX_CHARS} chars]"
    if not text:
        text = json.dumps(resp)[:500]
    return text


def _today() -> str:
    return date.today().isoformat()


def _in_days(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


@tool("get_market_tide")
def get_market_tide(date_param: str = "") -> str:
    """Market tide: total volume and net up/down premium, 5m intervals. Args: date_param 'YYYY-MM-DD' (optional, default today) — pass the scan date for as-of data."""
    args = {"interval_5m": False}
    if date_param:
        args["date"] = date_param
    return _projects(_uw().call_tool("get_market_tide", args))


@tool("get_market_state")
def get_market_state() -> str:
    """Market state snapshot: indexes, futures, macro context. CURRENT-ONLY (no historical mode)."""
    return _projects(_uw().call_tool("get_market_state", {}))


@tool("get_flow_alerts")
def get_flow_alerts(min_premium: str = "250000", is_sweep: bool = True,
                    limit: int = 50, ticker_symbol: str = "",
                    newer_than: str = "", older_than: str = "") -> str:
    """UW flow alerts, newest first. Default: sweeps with premium >= $250K. Args: min_premium, is_sweep, limit, ticker_symbol, newer_than/older_than 'YYYY-MM-DD' (optional — pass the scan date to window that day's tape; defaults to recent)."""
    args: dict = {"min_premium": min_premium, "is_sweep": str(is_sweep).lower(),
                  "limit": limit, "order": "premium"}
    if ticker_symbol:
        args["ticker_symbol"] = ticker_symbol
    if newer_than:
        args["newer_than"] = newer_than
    if older_than:
        args["older_than"] = older_than
    return _projects(_uw().call_tool("get_flow_alerts", args))


@tool("get_dark_pool_trades")
def get_dark_pool_trades(ticker_symbol: str = "", limit: int = 20,
                         newer_than: str = "", older_than: str = "") -> str:
    """Dark-pool prints. Args: ticker_symbol (optional filter), limit, newer_than/older_than 'YYYY-MM-DD' (optional — pass the scan date to window that day's prints; defaults to recent)."""
    args: dict = {"limit": limit}
    if ticker_symbol:
        args["ticker_symbol"] = ticker_symbol
    if newer_than:
        args["newer_than"] = newer_than
    if older_than:
        args["older_than"] = older_than
    return _projects(_uw().call_tool("get_dark_pool_trades", args))


@tool("get_insider_activity_by_ticker")
def get_insider_activity_by_ticker(ticker: str) -> str:
    """Insider buy/sell activity nets for a ticker. CURRENT-ONLY: 30-day lookback from today (no as-of mode). Args: ticker."""
    return _projects(_uw().call_tool("get_insider_activity_by_ticker", {"ticker": ticker}))


@tool("get_gex_levels")
def get_gex_levels(ticker: str, date_param: str = "") -> str:
    """Gamma exposure levels (dealer walls/flip point) for a ticker. Args: ticker, date_param 'YYYY-MM-DD' (optional — pass the scan date for as-of levels; defaults to last open market date)."""
    args: dict = {"ticker": ticker}
    if date_param:
        args["date"] = date_param
    return _projects(_uw().call_tool("get_gex_levels", args))


@tool("get_max_pain")
def get_max_pain(ticker: str, date_param: str = "") -> str:
    """Option-chain max pain level for a ticker. Args: ticker, date_param 'YYYY-MM-DD' (optional — pass the scan date for as-of pain; defaults to last open market date)."""
    args: dict = {"ticker": ticker}
    if date_param:
        args["date"] = date_param
    return _projects(_uw().call_tool("get_max_pain", args))


@tool("get_options_chain")
def get_options_chain(ticker: str, limit: int = 30) -> str:
    """Option chain snapshot (ATM context). CURRENT-ONLY (no historical mode). Args: ticker, limit."""
    return _projects(_uw().call_tool("get_options_chain", {"ticker": ticker, "limit": limit}))


@tool("get_upcoming_earnings")
def get_upcoming_earnings(ticker: str = "", min_date: str = "",
                          max_date: str = "", limit: int = 14) -> str:
    """Upcoming earnings calendar, window-limited. Args: ticker (optional), min_date/max_date 'YYYY-MM-DD' (optional — pass the scan date as min_date for as-of data; defaults to today), limit."""
    if not min_date:
        min_date = _today()
    if not max_date:
        max_date = (date.fromisoformat(min_date) + timedelta(days=10)).isoformat()
    args: dict = {"limit": limit, "min_date": min_date, "max_date": max_date}
    if ticker:
        args["ticker"] = ticker
    return _projects(_uw().call_tool("get_upcoming_earnings", args))


@tool("get_recent_congress_trades")
def get_recent_congress_trades(ticker_symbol: str = "", date_param: str = "",
                               limit: int = 20) -> str:
    """Recent congress member trades. Args: ticker_symbol (optional filter), date_param 'YYYY-MM-DD' (optional — latest transaction date; pass the scan date for as-of data), limit."""
    args: dict = {"limit": limit}
    if ticker_symbol:
        args["ticker"] = ticker_symbol
    if date_param:
        args["date"] = date_param
    return _projects(_uw().call_tool("get_recent_congress_trades", args))


UW_TOOLS = [
    get_market_tide, get_market_state, get_flow_alerts, get_dark_pool_trades,
    get_insider_activity_by_ticker, get_gex_levels, get_max_pain,
    get_options_chain, get_upcoming_earnings, get_recent_congress_trades,
]
