"""Chat endpoint: streams agent events as Server-Sent Events."""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.agent.agent import run_agent
from app.core.errors import NotFoundError
from app.schemas.api import ChatRequest
from app.storage.db import get_db

router = APIRouter(prefix="/chat", tags=["chat"])
log = logging.getLogger(__name__)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _title_from(message: str) -> str:
    text = " ".join(message.split())
    return (text[:57] + "...") if len(text) > 60 else text or "New chat"


async def _stream(body: ChatRequest) -> AsyncIterator[str]:
    db = get_db()
    try:
        if body.conversation_id:
            conv = await run_in_threadpool(db.get_conversation, body.conversation_id)
        else:
            conv = await run_in_threadpool(db.create_conversation, _title_from(body.message))
            conv["messages"] = []
        if conv["title"] == "New chat" and not conv["messages"]:
            conv = await run_in_threadpool(db.rename_conversation, conv["id"], _title_from(body.message))

        attachments: list[dict[str, Any]] = []
        for aid in body.attachment_ids:
            up = await run_in_threadpool(db.get_upload, aid)
            attachments.append(up)
        attachment_meta = [{"id": a["id"], "filename": a["filename"], "kind": a["kind"], "size": a["size"], "preview": a.get("preview")} for a in attachments]

        history = conv["messages"]
        user_msg = await run_in_threadpool(db.add_message, conv["id"], "user", body.message, attachment_meta)
        yield _sse("meta", {"conversation_id": conv["id"], "title": conv["title"], "user_message_id": user_msg["id"]})

        final: dict[str, Any] | None = None
        async for ev in run_agent(body.message, history, attachments):
            if ev.type == "done":
                final = ev.data
                break
            if ev.type == "error":
                msg = await run_in_threadpool(db.add_message, conv["id"], "assistant", ev.data.get("message", "Error"), [], [], ev.data.get("message"))
                yield _sse("error", {"message": ev.data.get("message"), "message_id": msg["id"]})
                return
            yield _sse(ev.type, ev.data)

        assert final is not None
        assistant = await run_in_threadpool(db.add_message, conv["id"], "assistant", final["content"], [], final.get("tool_calls", []))
        saved_datasets = []
        for ds in final.get("datasets", []):
            saved = await run_in_threadpool(db.save_dataset, assistant["id"], ds["title"], ds["columns"], ds["rows"], ds.get("summary"))
            saved_datasets.append(saved)
        assistant["datasets"] = saved_datasets
        yield _sse("done", {"message": assistant, "conversation_id": conv["id"], "title": conv["title"]})
    except NotFoundError as exc:
        yield _sse("error", {"message": exc.message})
    except Exception as exc:  # noqa: BLE001
        log.exception("Chat stream failed")
        yield _sse("error", {"message": f"Unexpected error: {exc}"})


@router.post("")
async def chat(body: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream(body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
