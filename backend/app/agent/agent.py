"""AI agent: OpenAI tool-calling loop over the ERPNext service layer.

Yields streaming events consumed by the chat SSE endpoint:
  status  - progress text ("Fetching sales data...")
  token   - a chunk of the final answer
  reset   - discard tokens streamed so far (model decided to call tools after all)
  tool    - a tool call finished (name, ok, row count)
  done    - final content + datasets + tool call log
  error   - fatal error message
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from openai import APIError, AsyncOpenAI

from app.agent.guard import is_erpnext_related
from app.agent.prompts import OFF_TOPIC_REPLY, build_system_prompt
from app.core.config import get_settings
from app.core.errors import AppError
from app.files.tools import TOOLS as FILE_TOOLS
from app.services.erpnext.client import get_client
from app.services.erpnext.context import get_site_context, load_site_context
from app.services.erpnext.registry import get_registry
from app.services.erpnext.tools import ToolResult

log = logging.getLogger(__name__)

STATUS_LABELS = {
    "sales": "Fetching sales data",
    "pos": "Fetching POS data",
    "stock": "Checking stock levels",
    "accounts": "Reading accounts",
    "purchase": "Fetching purchase data",
    "parties": "Looking up customer/supplier records",
    "manufacturing": "Fetching manufacturing data",
    "organization": "Reading organization masters",
    "generic": "Querying ERPNext",
    "files": "Analyzing uploaded file",
}


@dataclass
class AgentEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dataset:
    title: str
    columns: list[str]
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    tool: str

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "columns": self.columns, "rows": self.rows, "summary": self.summary, "tool": self.tool}


_openai: AsyncOpenAI | None = None


def get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _openai


def _registry_with_file_tools():
    reg = get_registry()
    for t in FILE_TOOLS:
        if reg.get(t.name) is None:
            t.module = "files"
            reg.register(t)
    return reg


def _history_messages(history: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in history[-limit:]:
        if m.get("role") not in ("user", "assistant") or m.get("error"):
            continue
        content = str(m.get("content") or "")
        if m.get("role") == "user" and m.get("attachments"):
            marks = "\n".join(f"[Attached file: {a.get('filename')} (file_id={a.get('id')}, {a.get('kind')})]" for a in m["attachments"])
            content = f"{content}\n{marks}"
        if content.strip():
            out.append({"role": m["role"], "content": content})
    return out


def _user_content(message: str, attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return message
    blocks = []
    for a in attachments:
        blocks.append(f"[Attached file: {a.get('filename')} (file_id={a.get('id')}, type={a.get('kind')})]\n{a.get('context') or ''}")
    return f"{message}\n\n" + "\n\n".join(blocks)


def _dataset_from_result(name: str, result: ToolResult) -> Dataset | None:
    if not result.rows and not result.summary:
        return None
    columns = result.columns or (list(result.rows[0].keys()) if result.rows else [])
    return Dataset(title=result.title or name.replace("_", " ").title(), columns=columns, rows=result.rows, summary=result.summary, tool=name)


async def run_agent(
    message: str,
    history: list[dict[str, Any]],
    attachments: list[dict[str, Any]] | None = None,
) -> AsyncIterator[AgentEvent]:
    settings = get_settings()
    attachments = attachments or []
    client = get_openai()
    ctx = get_site_context()
    if not ctx.loaded:
        ctx = await load_site_context()

    yield AgentEvent("status", {"text": "Checking question"})
    if not await is_erpnext_related(client, message, history, bool(attachments)):
        yield AgentEvent("token", {"text": OFF_TOPIC_REPLY})
        yield AgentEvent("done", {"content": OFF_TOPIC_REPLY, "datasets": [], "tool_calls": [], "off_topic": True})
        return

    registry = _registry_with_file_tools()
    tools_schema = registry.openai_schemas()
    erp = get_client()

    messages: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt(ctx, bool(attachments))}]
    messages += _history_messages(history)
    messages.append({"role": "user", "content": _user_content(message, attachments)})

    datasets: list[Dataset] = []
    tool_log: list[dict[str, Any]] = []
    final_content = ""

    for iteration in range(settings.max_agent_iterations + 1):
        last_round = iteration == settings.max_agent_iterations
        yield AgentEvent("status", {"text": "Thinking" if iteration == 0 else "Composing answer"})
        try:
            stream = await client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                tools=tools_schema if not last_round else None,
                tool_choice="auto" if not last_round else None,
                temperature=0.1,
                stream=True,
            )
        except APIError as exc:
            log.exception("OpenAI error")
            yield AgentEvent("error", {"message": f"AI service error: {getattr(exc, 'message', str(exc))}"})
            return

        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason = None
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                content_parts.append(delta.content)
                yield AgentEvent("token", {"text": delta.content})
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_calls.setdefault(tc.index, {"id": tc.id or "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
            if choice.finish_reason:
                finish_reason = choice.finish_reason

        content = "".join(content_parts)
        if not tool_calls or finish_reason == "stop" and not tool_calls:
            final_content = content.strip()
            break

        # Model wants tools: discard any partial prose that was streamed.
        if content:
            yield AgentEvent("reset")

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"}}
                for _, tc in sorted(tool_calls.items())
            ],
        }
        messages.append(assistant_msg)

        for _, tc in sorted(tool_calls.items()):
            name = tc["name"]
            tool = registry.get(name)
            label = STATUS_LABELS.get(tool.module if tool else "generic", "Querying ERPNext")
            yield AgentEvent("status", {"text": label})
            try:
                arguments = json.loads(tc["arguments"] or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
            except ValueError as exc:
                payload: dict[str, Any] = {"error": f"Invalid tool arguments: {exc}"}
                ok = False
                arguments = {}
            else:
                try:
                    if tool is None:
                        raise KeyError(f"Unknown tool {name}")
                    result = await tool.run(erp, **arguments)
                    payload = result.to_model_payload(settings.max_tool_rows)
                    ds = _dataset_from_result(name, result)
                    if ds:
                        datasets.append(ds)
                    ok = True
                except AppError as exc:
                    payload = {"error": exc.message}
                    ok = False
                except Exception as exc:  # noqa: BLE001 - surface to the model
                    log.exception("Tool %s failed", name)
                    payload = {"error": f"{type(exc).__name__}: {exc}"}
                    ok = False
            tool_log.append({"name": name, "arguments": arguments, "ok": ok, "rows": payload.get("row_count", 0) if ok else 0, "error": payload.get("error")})
            yield AgentEvent("tool", tool_log[-1])
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(payload, default=str)})

    if not final_content:
        final_content = "I could not produce an answer from the ERPNext data for this question. Please rephrase or narrow the period."
        yield AgentEvent("token", {"text": final_content})

    yield AgentEvent("done", {"content": final_content, "datasets": [d.to_dict() for d in datasets], "tool_calls": tool_log, "off_topic": False})
