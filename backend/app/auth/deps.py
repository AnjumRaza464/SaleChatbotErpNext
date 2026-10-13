"""FastAPI dependencies for authentication and module authorization."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool

from app.agent.scope import ADMIN_MODULE, MODULES, is_valid_module
from app.auth.security import SESSION_COOKIE, decode_session_token
from app.core.errors import AppError
from app.storage.db import get_db


class AuthError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


def user_modules(user: dict[str, Any]) -> list[str]:
    """Modules the user may open. Admins get the four tabs plus 'all'."""
    if user.get("is_admin"):
        return [*MODULES, ADMIN_MODULE]
    return list(user.get("modules") or [])


def user_can(user: dict[str, Any], module: str) -> bool:
    return is_valid_module(module) and module in user_modules(user)


async def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthError("Please sign in.")
    payload = decode_session_token(token)
    if not payload or not payload.get("sub"):
        raise AuthError("Your session has expired. Please sign in again.")
    db = get_db()
    user = None
    if payload.get("email"):
        user = await run_in_threadpool(db.get_user_by_email, payload["email"])
    if user is None:
        user = await run_in_threadpool(db.get_user, payload["sub"])
    if not user or not user.get("is_active"):
        raise AuthError("This account is disabled.")
    return user


async def current_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise ForbiddenError("Administrator access required.")
    return user


def assert_module(user: dict[str, Any], module: str | None) -> str:
    """Validate a module name for this user, raising 403 when not permitted."""
    if not module or not is_valid_module(module):
        raise ForbiddenError(f"A valid module ({', '.join(MODULES)}) is required.")
    if not user_can(user, module):
        raise ForbiddenError(f"You do not have access to the {module} module.")
    return module
