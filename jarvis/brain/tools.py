"""The fixed tool set Claude may call. No generic tools (shell, files, HTTP) ever go here."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler


def schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    """Strict-mode friendly object schema."""
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        """Name / description / JSON schema, shared by the API backend and the MCP bridge."""
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
        ]

    def for_messages_api(self) -> list[dict[str, Any]]:
        return [{**d, "strict": True} for d in self.describe()]

    async def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Run a tool; returns (JSON text, is_error). Never raises."""
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"unknown tool {name}"}), True
        try:
            result = await tool.handler(args or {})
        except Exception as e:  # tool bugs become tool errors, not crashes
            log.exception("tool %s failed", name)
            return json.dumps({"error": str(e)}, ensure_ascii=False), True
        return json.dumps(result, ensure_ascii=False, default=str), False
