"""Minimal MCP stdio server exposing Jarvis's tools to Claude Code.

Claude Code launches this process; it forwards tools/list and tools/call to the running
Jarvis server over loopback HTTP (authenticated with a per-run token). Stdlib only, so it
starts fast on the old desk Mac.

    python -m jarvis.brain.mcp_bridge   (env: JARVIS_TOOLS_URL, JARVIS_TOOLS_TOKEN)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
TIMEOUT = 20


class JarvisClient:
    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.token = token

    def _request(self, path: str, body: dict[str, Any] | None = None) -> Any:
        req = urllib.request.Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())

    def list_tools(self) -> list[dict[str, Any]]:
        return self._request("/api/tools")

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return self._request(f"/api/tools/{name}", {"arguments": args})


def handle(message: dict[str, Any], client: JarvisClient) -> dict[str, Any] | None:
    """Handle one JSON-RPC message; returns a response, or None for notifications."""
    method = message.get("method")
    msg_id = message.get("id")
    if msg_id is None:
        return None  # notifications (e.g. notifications/initialized) need no reply

    def ok(result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def fail(code: int, text: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    params = message.get("params") or {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return ok(
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "jarvis", "version": "0.2.0"},
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        try:
            tools = client.list_tools()
        except (urllib.error.URLError, OSError) as e:
            return fail(-32000, f"jarvis server unreachable: {e}")
        return ok(
            {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]} for t in tools]}
        )
    if method == "tools/call":
        try:
            result = client.call_tool(str(params.get("name")), params.get("arguments") or {})
        except (urllib.error.URLError, OSError) as e:
            return ok({"content": [{"type": "text", "text": f"jarvis server unreachable: {e}"}], "isError": True})
        return ok({"content": [{"type": "text", "text": result["content"]}], "isError": bool(result.get("is_error"))})
    return fail(-32601, f"method not found: {method}")


def serve(stdin: Any, stdout: Any, client: JarvisClient, log: Callable[[str], None]) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log(f"bad json: {line[:200]}")
            continue
        response = handle(message, client)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> None:
    url = os.environ.get("JARVIS_TOOLS_URL", "http://127.0.0.1:8765")
    token = os.environ.get("JARVIS_TOOLS_TOKEN", "")
    serve(sys.stdin, sys.stdout, JarvisClient(url, token), lambda m: print(m, file=sys.stderr))


if __name__ == "__main__":
    main()
