"""FastAPI application entry point."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import admin, auth, chat, conversations, export, health, transcribe, uploads
from app.agent.scope import MODULES
from app.auth.security import hash_password, verify_password
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.services.erpnext.client import close_client
from app.services.erpnext.context import load_site_context
from app.services.erpnext.registry import get_registry
from app.storage.db import close_db, get_db

log = logging.getLogger(__name__)


def _sync_env_user(db, email: str, password: str, full_name: str, modules: list[str], is_admin: bool) -> None:
    """Create the user if missing; otherwise make sure the password from the
    environment is the one in force (the environment is the source of truth on
    hosts where the database is ephemeral)."""
    existing = db.get_user_by_email(email)
    if existing is None:
        db.create_user(email, full_name, hash_password(password), modules, is_admin)
        log.info("Created user %s modules=%s admin=%s", email, modules, is_admin)
    elif not verify_password(password, existing["password_hash"]):
        db.update_user(existing["id"], password_hash=hash_password(password))
        log.info("Updated password for %s from environment", email)


def _bootstrap_admin(db, settings) -> None:
    """Ensure the administrator from ADMIN_EMAIL / ADMIN_PASSWORD and the users
    from SEED_USERS exist with the configured passwords (idempotent)."""
    if settings.admin_password:
        _sync_env_user(db, settings.admin_email, settings.admin_password, settings.admin_name, [], True)
    elif db.count_users() == 0:
        log.error("No users exist and ADMIN_PASSWORD is not set. Add ADMIN_EMAIL and ADMIN_PASSWORD to backend/.env to create the first administrator.")
    if not settings.seed_users.strip():
        return
    try:
        seeds = json.loads(settings.seed_users)
        assert isinstance(seeds, list)
    except Exception as exc:  # noqa: BLE001
        log.error("SEED_USERS is not a valid JSON list: %s", exc)
        return
    for s in seeds:
        email = str(s.get("email", "")).strip().lower()
        password = str(s.get("password", ""))
        if not email or len(password) < 8:
            continue
        modules = [m for m in s.get("modules", []) if m in MODULES]
        _sync_env_user(db, email, password, s.get("full_name") or email.split("@")[0], modules, bool(s.get("is_admin")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    db = get_db()
    _bootstrap_admin(db, settings)
    if not settings.session_secret:
        log.warning("SESSION_SECRET is not set; a random secret is used and sessions reset on every restart.")
    get_registry()
    ctx = await load_site_context()
    if ctx.loaded:
        log.info("Connected to ERPNext %s (company=%s, currency=%s, tz=%s)", ctx.erpnext_version, ctx.default_company, ctx.currency, ctx.time_zone)
    else:
        log.warning("ERPNext site context not loaded: %s", ctx.error)
    yield
    await close_client()
    close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "Invalid request", "errors": exc.errors()})

    api_prefix = "/api"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(conversations.router, prefix=api_prefix)
    app.include_router(chat.router, prefix=api_prefix)
    app.include_router(uploads.router, prefix=api_prefix)
    app.include_router(export.router, prefix=api_prefix)
    app.include_router(transcribe.router, prefix=api_prefix)
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)
    return app


app = create_app()
