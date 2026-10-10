"""Login / logout / current user."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.auth.deps import AuthError, current_user, user_modules
from app.auth.security import SESSION_COOKIE, create_session_token, login_throttle, verify_password
from app.core.config import get_settings
from app.schemas.api import LoginRequest, UserOut
from app.storage.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "is_admin": user["is_admin"],
        "is_active": user["is_active"],
        "modules": user_modules(user),
        "created_at": user.get("created_at"),
    }


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    key = f"{(request.client.host if request.client else '?')}|{body.email.strip().lower()}"
    if login_throttle.blocked(key):
        raise AuthError("Too many failed attempts. Try again in a few minutes.")
    db = get_db()
    user = await run_in_threadpool(db.get_user_by_email, body.email)
    ok = bool(user) and user["is_active"] and await run_in_threadpool(verify_password, body.password, user["password_hash"])
    if not ok:
        login_throttle.record_failure(key)
        await run_in_threadpool(db.add_audit, user["id"] if user else None, None, "login_failed", body.email)
        raise AuthError("Invalid email or password.")
    login_throttle.reset(key)
    token = create_session_token(user["id"])
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax", secure=secure, max_age=get_settings().session_hours * 3600, path="/",
    )
    await run_in_threadpool(db.add_audit, user["id"], None, "login", None)
    return user_out(user)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user_out(user)
