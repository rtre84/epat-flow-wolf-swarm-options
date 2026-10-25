"""CrewAI tool wrappers over the UW MCP client.

Each tool is a thin, JSON-string-in/JSON-string-out projection with a size cap
(agent context windows are precious). Real parameter names verified live
against the server's tools/list. Rate discipline: these serialize through one
client; scans stay well under UW Basic's 120 req/min.
"""
import json
from datetime import date, timedelta

from crewai.tools import tool

from swarm.tools.uw import UWMCPClient

_client = UWMCPClient()
_client.initialize()

MAX_CHARS = 6000


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
    """Market tide: total volume and net up/down premium, 5m intervals. Args: date_param 'YYYY-MM-DD' (optional, default today)."""
    args = {"interval_5m": False}
    if date_param:
        args["date"] = date_param
    return _projects(_client.call_tool("get_market_tide", args))


@tool("get_market_state")
def get_market_state() -> str:
    """Market state snapshot: indexes, futures, macro context."""
    return _projects(_client.call_tool("get_market_state", {}))


@tool("get_flow_alerts")
def get_flow_alerts(min_premium: str = "250000", is_sweep: bool = True,
                    limit: int = 50, ticker_symbol: str = "") -> str:
    """UW flow alerts, newest first. Default: sweeps with premium >= $250K. Args: min_premium, is_sweep, limit, ticker_symbol (optional)."""
    args: dict = {"min_premium": min_premium, "is_sweep": str(is_sweep).lower(),
                  "limit": limit, "order": "premium"}
    if ticker_symbol:
        args["ticker_symbol"] = ticker_symbol
    return _projects(_client.call_tool("get_flow_alerts", args))


@tool("get_dark_pool_trades")
def get_dark_pool_trades(ticker_symbol: str = "", limit: int = 20) -> str:
    """Recent dark-pool prints. Args: ticker_symbol (optional filter), limit."""
    args: dict = {"limit": limit}
    if ticker_symbol:
        args["ticker_symbol"] = ticker_symbol
    return _projects(_client.call_tool("get_dark_pool_trades", args))


@tool("get_insider_activity_by_ticker")
def get_insider_activity_by_ticker(ticker: str) -> str:
    """Insider buy/sell activity nets for a ticker. Args: ticker."""
    return _projects(_client.call_tool("get_insider_activity_by_ticker", {"ticker": ticker}))


@tool("get_gex_levels")
def get_gex_levels(ticker: str) -> str:
    """Gamma exposure levels (dealer walls/flip point) for a ticker. Args: ticker."""
    return _projects(_client.call_tool("get_gex_levels", {"ticker": ticker}))


@tool("get_max_pain")
def get_max_pain(ticker: str) -> str:
    """Option-chain max pain level for a ticker. Args: ticker."""
    return _projects(_client.call_tool("get_max_pain", {"ticker": ticker}))


@tool("get_options_chain")
def get_options_chain(ticker: str, limit: int = 30) -> str:
    """Option chain snapshot (ATM context). Args: ticker, limit."""
    return _projects(_client.call_tool("get_options_chain", {"ticker": ticker, "limit": limit}))


@tool("get_upcoming_earnings")
def get_upcoming_earnings(ticker: str = "", max_date: str = "", limit: int = 14) -> str:
    """Upcoming earnings calendar, window-limited. Args: ticker (optional), max_date (YYYY-MM-DD), limit."""
    args: dict = {"limit": limit, "min_date": _today(), "max_date": max_date or _in_days(10)}
    if ticker:
        args["ticker"] = ticker
    return _projects(_client.call_tool("get_upcoming_earnings", args))


@tool("get_recent_congress_trades")
def get_recent_congress_trades(ticker: str = "") -> str:
    """Recent congress member trades. Args: ticker (optional filter)."""
    args: dict = {"limit": 20}
    if ticker:
        args["ticker"] = ticker
    return _projects(_client.call_tool("get_recent_congress_trades", args))


UW_TOOLS = [
    get_market_tide, get_market_state, get_flow_alerts, get_dark_pool_trades,
    get_insider_activity_by_ticker, get_gex_levels, get_max_pain,
    get_options_chain, get_upcoming_earnings, get_recent_congress_trades,
]
