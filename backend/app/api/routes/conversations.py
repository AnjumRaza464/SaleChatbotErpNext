"""Conversation history, scoped to the signed-in user and a module."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.concurrency import run_in_threadpool

from app.auth.deps import assert_module, current_user, user_modules
from app.schemas.api import ConversationCreate, ConversationDetail, ConversationOut, ConversationRename
from app.storage.db import get_db

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    search: str | None = Query(default=None, max_length=200),
    module: str | None = Query(default=None, max_length=20),
    user: dict[str, Any] = Depends(current_user),
) -> list[dict]:
    if module:
        assert_module(user, module)
        return await run_in_threadpool(get_db().list_conversations, search, 200, user["id"], module)
    rows = await run_in_threadpool(get_db().list_conversations, search, 200, user["id"], None)
    allowed = set(user_modules(user))
    return [r for r in rows if r.get("module") in allowed]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(body: ConversationCreate | None = None, user: dict[str, Any] = Depends(current_user)) -> dict:
    title = body.title if body else "New chat"
    module = assert_module(user, body.module if body else None)
    return await run_in_threadpool(get_db().create_conversation, title, user["id"], module)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, user: dict[str, Any] = Depends(current_user)) -> dict:
    conv = await run_in_threadpool(get_db().get_conversation, conversation_id, user["id"])
    assert_module(user, conv.get("module"))
    conv["message_count"] = len(conv["messages"])
    return conv


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def rename_conversation(conversation_id: str, body: ConversationRename, user: dict[str, Any] = Depends(current_user)) -> dict:
    conv = await run_in_threadpool(get_db().rename_conversation, conversation_id, body.title, user["id"])
    conv["message_count"] = len(conv["messages"])
    return conv


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, user: dict[str, Any] = Depends(current_user)) -> None:
    await run_in_threadpool(get_db().delete_conversation, conversation_id, user["id"])
