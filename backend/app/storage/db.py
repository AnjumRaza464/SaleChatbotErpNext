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
from app.core.errors import NotFoundError, ValidationError

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
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_modules (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    PRIMARY KEY (user_id, module)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    module TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at);
"""

# Columns added to pre-existing tables (idempotent migrations).
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("conversations", "user_id", "TEXT"),
    ("conversations", "module", "TEXT NOT NULL DEFAULT 'all'"),
    ("uploads", "user_id", "TEXT"),
]


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
            self._migrate()

    def _migrate(self) -> None:
        for table, column, decl in _MIGRATIONS:
            cols = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ users
    def _user_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        u = dict(row)
        u["is_admin"] = bool(u["is_admin"])
        u["is_active"] = bool(u["is_active"])
        mods = self._conn.execute("SELECT module FROM user_modules WHERE user_id = ? ORDER BY module", (u["id"],)).fetchall()
        u["modules"] = [m["module"] for m in mods]
        return u

    def count_users(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, email: str, full_name: str, password_hash: str, modules: list[str], is_admin: bool = False) -> dict[str, Any]:
        uid, ts = new_id(), _now()
        email = email.strip().lower()
        with self._lock:
            if self._conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise ValidationError("A user with this email already exists.")
            self._conn.execute(
                "INSERT INTO users (id, email, full_name, password_hash, is_admin, is_active, created_at) VALUES (?,?,?,?,?,1,?)",
                (uid, email, full_name.strip()[:120], password_hash, int(is_admin), ts),
            )
            self._conn.executemany("INSERT OR IGNORE INTO user_modules VALUES (?,?)", [(uid, m) for m in modules])
            self._conn.commit()
        return self.get_user(uid)  # type: ignore[return-value]

    def get_user(self, uid: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
            return self._user_from_row(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            return self._user_from_row(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
            return [self._user_from_row(r) for r in rows]

    def update_user(
        self,
        uid: str,
        full_name: str | None = None,
        modules: list[str] | None = None,
        is_admin: bool | None = None,
        is_active: bool | None = None,
        password_hash: str | None = None,
    ) -> dict[str, Any]:
        sets: list[str] = []
        params: list[Any] = []
        if full_name is not None:
            sets.append("full_name = ?"); params.append(full_name.strip()[:120])
        if is_admin is not None:
            sets.append("is_admin = ?"); params.append(int(is_admin))
        if is_active is not None:
            sets.append("is_active = ?"); params.append(int(is_active))
        if password_hash is not None:
            sets.append("password_hash = ?"); params.append(password_hash)
        with self._lock:
            if not self._conn.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
                raise NotFoundError("User not found")
            if sets:
                self._conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", [*params, uid])
            if modules is not None:
                self._conn.execute("DELETE FROM user_modules WHERE user_id = ?", (uid,))
                self._conn.executemany("INSERT OR IGNORE INTO user_modules VALUES (?,?)", [(uid, m) for m in modules])
            self._conn.commit()
        return self.get_user(uid)  # type: ignore[return-value]

    def delete_user(self, uid: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM conversations WHERE user_id = ?", (uid,))
            cur = self._conn.execute("DELETE FROM users WHERE id = ?", (uid,))
            self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("User not found")

    # -------------------------------------------------------------- audit log
    def add_audit(self, user_id: str | None, module: str | None, action: str, detail: str | None = None) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO audit_log VALUES (?,?,?,?,?,?)", (new_id(), user_id, module, action, (detail or "")[:2000], _now()))
            self._conn.commit()

    def list_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT a.*, u.email FROM audit_log a LEFT JOIN users u ON u.id = a.user_id ORDER BY a.created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- conversations
    def create_conversation(self, title: str = "New chat", user_id: str | None = None, module: str = "all") -> dict[str, Any]:
        cid, ts = new_id(), _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at, user_id, module) VALUES (?,?,?,?,?,?)",
                (cid, title[:120], ts, ts, user_id, module),
            )
            self._conn.commit()
        return {"id": cid, "title": title[:120], "created_at": ts, "updated_at": ts, "message_count": 0, "user_id": user_id, "module": module}

    def list_conversations(self, search: str | None = None, limit: int = 200, user_id: str | None = None, module: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count "
            "FROM conversations c WHERE 1=1"
        )
        params: list[Any] = []
        if user_id is not None:
            sql += " AND c.user_id = ?"
            params.append(user_id)
        if module is not None:
            sql += " AND c.module = ?"
            params.append(module)
        if search:
            sql += " AND (c.title LIKE ? OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.content LIKE ?))"
            params += [f"%{search}%", f"%{search}%"]
        sql += " ORDER BY c.updated_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_conversation(self, cid: str, user_id: str | None = None) -> dict[str, Any]:
        """Fetch a conversation; when ``user_id`` is given, only that owner's."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
        if not row or (user_id is not None and row["user_id"] != user_id):
            raise NotFoundError("Conversation not found")
        conv = dict(row)
        conv["messages"] = self.get_messages(cid)
        return conv

    def rename_conversation(self, cid: str, title: str, user_id: str | None = None) -> dict[str, Any]:
        self.get_conversation(cid, user_id)
        with self._lock:
            self._conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (title[:120], _now(), cid))
            self._conn.commit()
        return self.get_conversation(cid, user_id)

    def touch_conversation(self, cid: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), cid))
            self._conn.commit()

    def delete_conversation(self, cid: str, user_id: str | None = None) -> None:
        self.get_conversation(cid, user_id)
        with self._lock:
            self._conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
            self._conn.commit()

    def conversation_for_message(self, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT c.* FROM conversations c JOIN messages m ON m.conversation_id = c.id WHERE m.id = ?", (message_id,)
            ).fetchone()
        return dict(row) if row else None

    def conversation_for_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT c.* FROM conversations c JOIN messages m ON m.conversation_id = c.id JOIN datasets d ON d.message_id = m.id WHERE d.id = ?",
                (dataset_id,),
            ).fetchone()
        return dict(row) if row else None

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
    def save_upload(self, filename: str, path: str, kind: str, size: int, preview: str, context: str, user_id: str | None = None) -> dict[str, Any]:
        uid, ts = new_id(), _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO uploads (id, filename, path, kind, size, preview, context, created_at, user_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (uid, filename, path, kind, size, preview, context, ts, user_id),
            )
            self._conn.commit()
        return {"id": uid, "filename": filename, "kind": kind, "size": size, "preview": preview, "created_at": ts}

    def get_upload(self, uid: str, user_id: str | None = None) -> dict[str, Any]:
        """Fetch an upload; when ``user_id`` is given, only that owner's."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM uploads WHERE id = ?", (uid,)).fetchone()
        if not row or (user_id is not None and row["user_id"] != user_id):
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
