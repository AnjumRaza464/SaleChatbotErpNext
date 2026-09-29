"""Pydantic models for the HTTP API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DatasetOut(BaseModel):
    id: str
    title: str
    columns: list[str]
    row_count: int


class AttachmentOut(BaseModel):
    id: str
    filename: str
    kind: str
    size: int
    preview: str | None = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    attachments: list[AttachmentOut] = []
    tool_calls: list[dict[str, Any]] = []
    datasets: list[DatasetOut] = []
    error: str | None = None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = []


class ConversationCreate(BaseModel):
    title: str = "New chat"


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    attachment_ids: list[str] = []


class UploadOut(AttachmentOut):
    created_at: str


class ExportRequest(BaseModel):
    title: str = "ERPNext Export"
    columns: list[str] = []
    rows: list[dict[str, Any]]
    summary: dict[str, Any] = {}


class TranscriptionOut(BaseModel):
    text: str


class HealthOut(BaseModel):
    status: str
    erpnext: dict[str, Any]
    model: str
    tools: int
    modules: dict[str, list[str]]
