"""Administrator endpoints: user management and audit log."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.concurrency import run_in_threadpool

from app.agent.scope import MODULES
from app.api.routes.auth import user_out
from app.auth.deps import current_admin
from app.auth.security import hash_password
from app.core.errors import ValidationError
from app.schemas.api import UserCreate, UserOut, UserUpdate
from app.storage.db import get_db

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(current_admin)])


def _clean_modules(modules: list[str]) -> list[str]:
    bad = [m for m in modules if m not in MODULES]
    if bad:
        raise ValidationError(f"Unknown module(s): {', '.join(bad)}. Valid: {', '.join(MODULES)}")
    return sorted(set(modules))


@router.get("/modules")
async def list_modules() -> list[dict[str, str]]:
    return [{"key": k, **v} for k, v in MODULES.items()]


@router.get("/users", response_model=list[UserOut])
async def list_users() -> list[dict[str, Any]]:
    users = await run_in_threadpool(get_db().list_users)
    return [user_out(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, admin: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
    if len(body.password) < 8:
        raise ValidationError("Password must be at least 8 characters.")
    db = get_db()
    user = await run_in_threadpool(db.create_user, body.email, body.full_name, hash_password(body.password), _clean_modules(body.modules), body.is_admin)
    await run_in_threadpool(db.add_audit, admin["id"], None, "user_created", f"{user['email']} modules={user['modules']} admin={user['is_admin']}")
    return user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: UserUpdate, admin: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
    db = get_db()
    if user_id == admin["id"] and (body.is_admin is False or body.is_active is False):
        raise ValidationError("You cannot remove your own administrator access or disable yourself.")
    if body.password is not None and len(body.password) < 8:
        raise ValidationError("Password must be at least 8 characters.")
    user = await run_in_threadpool(
        db.update_user,
        user_id,
        body.full_name,
        _clean_modules(body.modules) if body.modules is not None else None,
        body.is_admin,
        body.is_active,
        hash_password(body.password) if body.password else None,
    )
    await run_in_threadpool(db.add_audit, admin["id"], None, "user_updated", f"{user['email']} modules={user['modules']} admin={user['is_admin']} active={user['is_active']}")
    return user_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, admin: dict[str, Any] = Depends(current_admin)) -> None:
    if user_id == admin["id"]:
        raise ValidationError("You cannot delete your own account.")
    db = get_db()
    target = await run_in_threadpool(db.get_user, user_id)
    await run_in_threadpool(db.delete_user, user_id)
    await run_in_threadpool(db.add_audit, admin["id"], None, "user_deleted", target["email"] if target else user_id)


@router.get("/audit")
async def audit(limit: int = Query(default=200, le=1000)) -> list[dict[str, Any]]:
    return await run_in_threadpool(get_db().list_audit, limit)
