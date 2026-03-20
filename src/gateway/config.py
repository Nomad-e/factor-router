"""
src/gateway/config.py

Configuração central do gateway via Pydantic Settings.

As apps e as suas API Keys são geridas exclusivamente via base de dados
(tabelas gateway_apps e gateway_api_keys) através da Admin API.

NÃO existem GATEWAY_KEY_* neste ficheiro nem no .env.
A gestão de keys é feita via:
    POST /admin/apps                   — criar app
    POST /admin/apps/{id}/keys         — gerar key
    DELETE /admin/apps/{id}/keys/{kid} — revogar key

Variáveis obrigatórias no .env:
    OPENROUTER_API_KEY  — key do OpenRouter (nunca sai do gateway)
    DATABASE_URL        — postgresql+asyncpg://user:pass@host/db
    ADMIN_SECRET        — protege os endpoints /admin/*

Variáveis opcionais (têm default):
    PORT             — default 8003
    HOST             — default 0.0.0.0
    LOG_LEVEL        — default info
    UPSTREAM_TIMEOUT — default 120 (segundos)
    UPSTREAM_URL     — default https://openrouter.ai/api/v1
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── upstream provider ─────────────────────────────────────────────────
    openrouter_api_key: str = Field(
        ...,
        description="Key do OpenRouter — nunca sai do gateway",
    )
    upstream_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Base URL do provider upstream",
    )
    upstream_timeout: int = Field(
        default=120,
        description="Timeout em segundos para calls ao upstream",
    )

    # ── base de dados ─────────────────────────────────────────────────────
    database_url: str = Field(
        ...,
        description="PostgreSQL connection string",
    )

    # ── admin ─────────────────────────────────────────────────────────────
    admin_secret: str = Field(
        ...,
        description="Secret para proteger os endpoints /admin/*",
    )

    # ── servidor ──────────────────────────────────────────────────────────
    host: str  = Field(default="0.0.0.0")
    port: int  = Field(default=8003)
    log_level: str = Field(default="info")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Singleton das settings — carregado uma vez, cacheado para sempre.
    FastAPI injeta via Depends(get_settings).
    """
    return Settings()