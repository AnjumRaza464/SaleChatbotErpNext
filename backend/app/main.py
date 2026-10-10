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
from app.auth.security import hash_password
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.services.erpnext.client import close_client
from app.services.erpnext.context import load_site_context
from app.services.erpnext.registry import get_registry
from app.storage.db import close_db, get_db

log = logging.getLogger(__name__)


def _bootstrap_admin(db, settings) -> None:
    """Create the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD when no users
    exist, then any SEED_USERS that are missing (idempotent)."""
    if db.count_users() == 0:
        if not settings.admin_password:
            log.error("No users exist and ADMIN_PASSWORD is not set. Add ADMIN_EMAIL and ADMIN_PASSWORD to backend/.env to create the first administrator.")
        else:
            db.create_user(settings.admin_email, settings.admin_name, hash_password(settings.admin_password), [], is_admin=True)
            log.info("Created initial administrator %s", settings.admin_email)
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
        if not email or len(password) < 8 or db.get_user_by_email(email):
            continue
        modules = [m for m in s.get("modules", []) if m in MODULES]
        db.create_user(email, s.get("full_name") or email.split("@")[0], hash_password(password), modules, bool(s.get("is_admin")))
        log.info("Seeded user %s modules=%s", email, modules)


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
