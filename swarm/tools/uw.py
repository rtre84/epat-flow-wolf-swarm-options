"""Unusual Whales access: remote MCP (https://api.unusualwhales.com/api/mcp).

Phase 1 scope: verify auth + enumerate tools. Phase 2 wraps selected calls
as CrewAI @tool functions with the 120 req/min budget in mind (never
parallel-call more than ~30 in-flight; batch instead).
"""
import json
import os
import uuid

import httpx

MCP_URL = "https://api.unusualwhales.com/api/mcp"
PROTOCOL_VERSION = "2025-03-26"


class UWMCPClient:
    """Minimal streamable-HTTP MCP client for UW. No SDK dependency."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("UW_API_KEY")
        if not self.api_key:
            raise RuntimeError("UW_API_KEY is not set (see .env.example)")
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._session_id: str | None = None

    def _rpc(self, method: str, params: dict, rpc_id: int | None = None) -> dict:
        body = {
            "jsonrpc": "2.0",
            "id": rpc_id if rpc_id is not None else 1,
            "method": method,
            "params": params,
        }
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        resp = httpx.post(MCP_URL, content=json.dumps(body), headers=headers, timeout=30)
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        text = resp.text
        if "text/event-stream" in resp.headers.get("content-type", ""):
            for line in text.splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload:
                        return json.loads(payload)
            raise RuntimeError(f"MCP SSE response had no data lines: {text[:200]}")
        return resp.json()

    def initialize(self) -> dict:
        resp = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "flowwolf", "version": "0.1.0"},
            },
        )
        self._rpc("notifications/initialized", {})
        return resp.get("result", {})

    def list_tools(self) -> list[str]:
        resp = self._rpc("tools/list", {})
        return [t["name"] for t in resp.get("result", {}).get("tools", [])]

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
            rpc_id=int(uuid.uuid1().node % 100000),
        )

    def smoke(self) -> dict:
        """Auth + tool-count + one live call. Raises on failure."""
        server = self.initialize()
        name = server.get("serverInfo", {}).get("name", "?")
        tools = self.list_tools()
        return {"server": name, "tool_count": len(tools), "first_tools": tools[:5]}
