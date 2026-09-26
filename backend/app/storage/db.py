"""SQLite persistence for conversations, messages, uploads and exportable datasets.

Plain ``sqlite3`` guarded by a lock; calls are cheap and run in FastAPI's
threadpool via ``run_in_threadpool`` from the routes.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import NotFoundError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    attachments TEXT NOT NULL DEFAULT '[]',
    tool_calls TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    preview TEXT,
    context TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    columns TEXT NOT NULL,
    rows TEXT NOT NULL,
    summary TEXT,
    row_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_datasets_msg ON datasets(message_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------- conversations
    def create_conversation(self, title: str = "New chat") -> dict[str, Any]:
        cid, ts = new_id(), _now()
        with self._lock:
            self._conn.execute("INSERT INTO conversations VALUES (?,?,?,?)", (cid, title[:120], ts, ts))
            self._conn.commit()
        return {"id": cid, "title": title[:120], "created_at": ts, "updated_at": ts, "message_count": 0}

    def list_conversations(self, search: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = (
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count "
            "FROM conversations c"
        )
        params: list[Any] = []
        if search:
            sql += (
                " WHERE c.title LIKE ? OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.content LIKE ?)"
            )
            params += [f"%{search}%", f"%{search}%"]
        sql += " ORDER BY c.updated_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_conversation(self, cid: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
        if not row:
            raise NotFoundError("Conversation not found")
        conv = dict(row)
        conv["messages"] = self.get_messages(cid)
        return conv

    def rename_conversation(self, cid: str, title: str) -> dict[str, Any]:
        with self._lock:
            cur = self._conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (title[:120], _now(), cid))
            self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("Conversation not found")
        return self.get_conversation(cid)

    def touch_conversation(self, cid: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), cid))
            self._conn.commit()

    def delete_conversation(self, cid: str) -> None:
        with self._lock:
            cur = self._conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("Conversation not found")

    # --------------------------------------------------------------- messages
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        mid, ts = new_id(), _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, attachments, tool_calls, error, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (mid, conversation_id, role, content, json.dumps(attachments or []), json.dumps(tool_calls or []), error, ts),
            )
            self._conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (ts, conversation_id))
            self._conn.commit()
        return self.get_message(mid)

    def get_message(self, mid: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
        if not row:
            raise NotFoundError("Message not found")
        return self._message_from_row(row)

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC", (conversation_id,)
            ).fetchall()
        return [self._message_from_row(r) for r in rows]

    def _message_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        m = dict(row)
        m["attachments"] = json.loads(m.get("attachments") or "[]")
        m["tool_calls"] = json.loads(m.get("tool_calls") or "[]")
        m["datasets"] = self.list_datasets_for_message(m["id"])
        return m

    # ---------------------------------------------------------------- uploads
    def save_upload(self, filename: str, path: str, kind: str, size: int, preview: str, context: str) -> dict[str, Any]:
        uid, ts = new_id(), _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO uploads VALUES (?,?,?,?,?,?,?,?)", (uid, filename, path, kind, size, preview, context, ts)
            )
            self._conn.commit()
        return {"id": uid, "filename": filename, "kind": kind, "size": size, "preview": preview, "created_at": ts}

    def get_upload(self, uid: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM uploads WHERE id = ?", (uid,)).fetchone()
        if not row:
            raise NotFoundError("Upload not found")
        return dict(row)

    # --------------------------------------------------------------- datasets
    def save_dataset(self, message_id: str | None, title: str, columns: list[str], rows: list[dict[str, Any]], summary: dict[str, Any] | None) -> dict[str, Any]:
        did, ts = new_id(), _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?)",
                (did, message_id, title[:120], json.dumps(columns), json.dumps(rows, default=str), json.dumps(summary or {}, default=str), len(rows), ts),
            )
            self._conn.commit()
        return {"id": did, "title": title[:120], "columns": columns, "row_count": len(rows)}

    def attach_datasets(self, dataset_ids: list[str], message_id: str) -> None:
        if not dataset_ids:
            return
        with self._lock:
            self._conn.executemany("UPDATE datasets SET message_id = ? WHERE id = ?", [(message_id, d) for d in dataset_ids])
            self._conn.commit()

    def get_dataset(self, did: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM datasets WHERE id = ?", (did,)).fetchone()
        if not row:
            raise NotFoundError("Dataset not found")
        d = dict(row)
        d["columns"] = json.loads(d["columns"])
        d["rows"] = json.loads(d["rows"])
        d["summary"] = json.loads(d.get("summary") or "{}")
        return d

    def list_datasets_for_message(self, message_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, columns, row_count FROM datasets WHERE message_id = ? ORDER BY created_at ASC, rowid ASC", (message_id,)
            ).fetchall()
        return [{"id": r["id"], "title": r["title"], "columns": json.loads(r["columns"]), "row_count": r["row_count"]} for r in rows]

    def get_datasets_for_message(self, message_id: str) -> list[dict[str, Any]]:
        return [self.get_dataset(d["id"]) for d in self.list_datasets_for_message(message_id)]


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(get_settings().db_path)
    return _db


def close_db() -> None:
    global _db
    if _db is not None:
        _db.close()
        _db = None
