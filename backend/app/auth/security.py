"""Password hashing and signed session tokens."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

SESSION_COOKIE = "erp_session"
_generated_secret: str | None = None


def _secret() -> str:
    global _generated_secret
    s = get_settings().session_secret
    if s:
        return s
    if _generated_secret is None:
        _generated_secret = secrets.token_urlsafe(48)
    return _generated_secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_session_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(hours=get_settings().session_hours), "jti": secrets.token_hex(8)}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


class LoginThrottle:
    """Small in-memory limiter: at most ``limit`` failed logins per key per window."""

    def __init__(self, limit: int = 10, window_seconds: int = 900) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        self._hits[key] = hits
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, time.time())) >= self.limit

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.time()
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


login_throttle = LoginThrottle()
