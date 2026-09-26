"""ERPNext-only topic guard.

A cheap classification call decides whether the latest user message is about
ERPNext / the company's business data. Off-topic messages get the fixed reply
without ever reaching the main agent.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.agent.prompts import GUARD_PROMPT
from app.core.config import get_settings

log = logging.getLogger(__name__)


async def is_erpnext_related(client: AsyncOpenAI, message: str, history: list[dict[str, Any]], has_files: bool) -> bool:
    settings = get_settings()
    recent = [m for m in history if m.get("role") in ("user", "assistant")][-6:]
    context_lines = [f"{m['role']}: {str(m.get('content', ''))[:300]}" for m in recent]
    user_block = "Conversation so far:\n" + ("\n".join(context_lines) or "(none)")
    user_block += f"\n\nAttachments present: {'yes' if has_files else 'no'}\n\nLatest user message:\n{message}"
    try:
        resp = await client.chat.completions.create(
            model=settings.guard_model,
            temperature=0,
            max_completion_tokens=20,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": GUARD_PROMPT}, {"role": "user", "content": user_block}],
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return bool(data.get("erpnext_related", True))
    except Exception as exc:  # fail open: the main prompt also enforces the rule
        log.warning("Guard classification failed, allowing message: %s", exc)
        return True
