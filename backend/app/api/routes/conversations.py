from __future__ import annotations

from fastapi import APIRouter, Query, status
from fastapi.concurrency import run_in_threadpool

from app.schemas.api import ConversationCreate, ConversationDetail, ConversationOut, ConversationRename
from app.storage.db import get_db

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(search: str | None = Query(default=None, max_length=200)) -> list[dict]:
    return await run_in_threadpool(get_db().list_conversations, search)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(body: ConversationCreate | None = None) -> dict:
    title = body.title if body else "New chat"
    return await run_in_threadpool(get_db().create_conversation, title)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str) -> dict:
    conv = await run_in_threadpool(get_db().get_conversation, conversation_id)
    conv["message_count"] = len(conv["messages"])
    return conv


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def rename_conversation(conversation_id: str, body: ConversationRename) -> dict:
    conv = await run_in_threadpool(get_db().rename_conversation, conversation_id, body.title)
    conv["message_count"] = len(conv["messages"])
    return conv


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str) -> None:
    await run_in_threadpool(get_db().delete_conversation, conversation_id)
