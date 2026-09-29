"""Application settings. All secrets come from the environment / .env file."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
# On Vercel (and most serverless hosts) the project directory is read-only;
# only /tmp is writable, so runtime data (SQLite DB, uploads) goes there.
DEFAULT_DATA_DIR = Path("/tmp/erpnext-assistant") if os.environ.get("VERCEL") else BACKEND_DIR / "data"


class Settings(BaseSettings):
    """Runtime configuration. Values are read from (in priority order):
    process environment, backend/.env, project-root .env."""

    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ERPNext -------------------------------------------------------------
    erpnext_base_url: str = Field(
        validation_alias=AliasChoices("ERPNEXT_BASE_URL", "ERPNEXT_URL"),
    )
    erpnext_api_key: str = Field(validation_alias="ERPNEXT_API_KEY")
    erpnext_api_secret: str = Field(validation_alias="ERPNEXT_API_SECRET")
    erpnext_timeout_seconds: float = 60.0

    # LLM -----------------------------------------------------------------
    openai_api_key: str = Field(validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    openai_guard_model: str | None = Field(default=None, validation_alias="OPENAI_GUARD_MODEL")
    openai_transcribe_model: str = Field(default="gpt-4o-mini-transcribe", validation_alias="OPENAI_TRANSCRIBE_MODEL")

    # App -----------------------------------------------------------------
    app_name: str = "ERPNext AI Assistant"
    cors_origins: str = Field(default="http://localhost:3000", validation_alias="CORS_ORIGINS")
    data_dir: Path = Field(default=DEFAULT_DATA_DIR, validation_alias="DATA_DIR")
    max_upload_mb: int = Field(default=20, validation_alias="MAX_UPLOAD_MB")
    max_tool_rows: int = Field(default=200, validation_alias="MAX_TOOL_ROWS")
    max_agent_iterations: int = Field(default=8, validation_alias="MAX_AGENT_ITERATIONS")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @property
    def erpnext_url(self) -> str:
        return self.erpnext_base_url.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def guard_model(self) -> str:
        return self.openai_guard_model or self.openai_model


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings
