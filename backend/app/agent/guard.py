"""ERPNext-only topic guard with module scope.

A cheap classification call decides whether the latest user message is about
ERPNext / the company's business data, and whether it belongs to the module
(tab) the user is in. Off-topic messages get the fixed reply without ever
reaching the main agent; out-of-scope ones get the module refusal.

The guard is advisory: the registry's tool allowlist is what actually prevents
cross-module data access. The guard just avoids wasted tool calls and gives a
clean refusal message.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.agent.prompts import GUARD_PROMPT, GUARD_SCOPE_HINT
from app.agent.scope import ADMIN_MODULE, MODULES
from app.core.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class GuardVerdict:
    related: bool = True
    in_scope: bool = True
    area: str = ""


async def classify(client: AsyncOpenAI, message: str, history: list[dict[str, Any]], has_files: bool, module: str = ADMIN_MODULE) -> GuardVerdict:
    settings = get_settings()
    recent = [m for m in history if m.get("role") in ("user", "assistant")][-6:]
    context_lines = [f"{m['role']}: {str(m.get('content', ''))[:300]}" for m in recent]
    system = GUARD_PROMPT
    if module in MODULES:
        system += GUARD_SCOPE_HINT.format(module=module, description=MODULES[module]["description"])
    user_block = "Conversation so far:\n" + ("\n".join(context_lines) or "(none)")
    user_block += f"\n\nAttachments present: {'yes' if has_files else 'no'}\n\nLatest user message:\n{message}"
    try:
        resp = await client.chat.completions.create(
            model=settings.guard_model,
            temperature=0,
            max_completion_tokens=40,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_block}],
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        verdict = GuardVerdict(
            related=bool(data.get("erpnext_related", True)),
            in_scope=bool(data.get("in_scope", True)) if module in MODULES else True,
            area=str(data.get("area") or ""),
        )
        return verdict
    except Exception as exc:  # fail open: the main prompt and tool allowlist also enforce the rules
        log.warning("Guard classification failed, allowing message: %s", exc)
        return GuardVerdict()


async def is_erpnext_related(client: AsyncOpenAI, message: str, history: list[dict[str, Any]], has_files: bool) -> bool:
    """Backwards-compatible helper."""
    return (await classify(client, message, history, has_files)).related
