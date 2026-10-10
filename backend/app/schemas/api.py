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
    module: str = "all"


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = []


class ConversationCreate(BaseModel):
    title: str = "New chat"
    module: str = "all"


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    attachment_ids: list[str] = []
    module: str = Field(default="all", max_length=20)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    is_admin: bool
    is_active: bool
    modules: list[str]
    created_at: str | None = None


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    modules: list[str] = []
    is_admin: bool = False


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str | None = Field(default=None, max_length=200)
    modules: list[str] | None = None
    is_admin: bool | None = None
    is_active: bool | None = None


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
