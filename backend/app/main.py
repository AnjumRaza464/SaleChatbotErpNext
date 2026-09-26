"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import chat, conversations, export, health, uploads
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.services.erpnext.client import close_client
from app.services.erpnext.context import load_site_context
from app.services.erpnext.registry import get_registry
from app.storage.db import close_db, get_db

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    get_db()
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
    return app


app = create_app()
