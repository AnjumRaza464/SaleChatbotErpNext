"""Tool registry: discovers every module in ``modules/`` and exposes its tools.

To add a new ERPNext module, create ``app/services/erpnext/modules/<name>.py``
with a ``TOOLS: list[Tool]`` attribute. Nothing else needs to change.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from app.services.erpnext import modules as modules_pkg
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.tools import Tool, ToolResult

log = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def load(self) -> None:
        self._tools.clear()
        for info in pkgutil.iter_modules(modules_pkg.__path__):
            if info.name.startswith("_") or info.name == "common":
                continue
            mod = importlib.import_module(f"{modules_pkg.__name__}.{info.name}")
            for tool in getattr(mod, "TOOLS", []):
                if tool.name in self._tools:
                    raise RuntimeError(f"Duplicate tool name '{tool.name}' in module {info.name}")
                tool.module = info.name
                self._tools[tool.name] = tool
        log.info("Loaded %d ERPNext tools from %d modules", len(self._tools), len({t.module for t in self._tools.values()}))

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    @property
    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def openai_schemas(self) -> list[dict[str, Any]]:
        return [t.openai_schema() for t in self._tools.values()]

    def modules(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for t in self._tools.values():
            out.setdefault(t.module, []).append(t.name)
        return out

    async def call(self, name: str, client: ERPNextClient, arguments: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool '{name}'")
        return await tool.run(client, **arguments)


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _registry.load()
    return _registry
