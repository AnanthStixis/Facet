"""Application configuration.

Everything the app needs to know about its environment is resolved here once,
at import time, and read from a single frozen settings object. No module reads
os.environ directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime ----------------------------------------------------------
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False

    # --- Product identity -------------------------------------------------
    product_name: str = "Facet"
    product_tagline: str = "Every relationship has more than one side."
    vendor_name: str = "Stixis AI Solutions"

    # --- Database ---------------------------------------------------------
    database_url: str
    alembic_database_url: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- Rate limiting / shared counters ----------------------------------
    # Empty means "use the in-process limiter". Correct for a single-worker
    # local run; must be set once more than one worker serves traffic, or each
    # worker enforces its own private limit.
    redis_url: str = ""

    # --- Security ---------------------------------------------------------
    secret_key: str
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    invite_token_ttl_hours: int = 72
    feedback_link_ttl_days: int = 30
    password_min_length: int = 8
    mfa_required_for_super_admin: bool = True
    login_max_attempts: int = 8
    login_lockout_seconds: int = 900
    cookie_secure: bool = False
    cookie_domain: str = ""

    # --- HTTP -------------------------------------------------------------
    # Kept as a raw string because pydantic-settings decodes list-typed fields
    # as JSON, which would force an awkward quoted-array literal in the .env.
    # The parsed form is exposed as `cors_origin_list`.
    cors_origins: str = "http://localhost:5174"
    public_app_url: str = "http://localhost:5174"
    public_api_url: str = "http://localhost:8010"

    # --- Email ------------------------------------------------------------
    email_backend: Literal["file", "smtp", "console", "azure", "resend"] = "file"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    email_from: str = "no-reply@facet.local"
    email_from_name: str = "Facet"

    # --- Storage ----------------------------------------------------------
    storage_backend: Literal["local", "azure"] = "local"
    storage_local_path: str = "var/storage"
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "facet-assets"
    logo_max_bytes: int = 2 * 1024 * 1024

    # --- AI ---------------------------------------------------------------
    ai_enabled: bool = False
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_deep: str = "gpt-4o"
    openai_model_embedding: str = "text-embedding-3-small"
    ai_monthly_token_budget_per_org: int = 2_000_000
    ai_min_responses_for_summary: int = 4

    # --- Exports ----------------------------------------------------------
    export_sync_row_limit: int = 5_000
    export_hard_row_limit: int = 250_000

    @property
    def outbox_path(self) -> Path:
        """Where the `file` email backend writes .eml files during development."""
        return BACKEND_ROOT / "var" / "outbox"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_local_path)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path

    @property
    def migration_url(self) -> str:
        return self.alembic_database_url or self.database_url.replace(
            "postgresql+asyncpg", "postgresql+psycopg"
        )

    def assert_production_safe(self) -> None:
        """Fail fast rather than run production on development defaults."""
        if not self.is_production:
            return
        problems: list[str] = []
        if "change-me" in self.secret_key or len(self.secret_key) < 32:
            problems.append("SECRET_KEY is a default or too short")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if self.debug:
            problems.append("DEBUG must be false in production")
        if any(o.startswith("http://") for o in self.cors_origin_list):
            problems.append("CORS_ORIGINS contains a non-HTTPS origin")
        if not self.redis_url:
            problems.append("REDIS_URL is required so rate limits are shared across workers")
        if self.email_backend in {"file", "console"}:
            problems.append("EMAIL_BACKEND must be a real transport in production")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    settings.assert_production_safe()
    return settings


settings = get_settings()
