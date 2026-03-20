"""
src/api/routes/usage.py

Endpoints de leitura do centro de custos.
GET /usage/logs   — lista de registos por turno
GET /usage/stats  — agregados por modelo, empresa e app

Controlo de acesso:
    - Bearer <app_key>   → só vê os logs da sua própria app (app_id forçado)
    - X-Admin-Secret     → vê tudo, sem filtros de app
"""
from __future__ import annotations

from typing import Annotated, Optional
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.gateway.config import Settings, get_settings
from src.gateway.key_store import get_key_store
from src.usage.service import get_usage_logs, get_usage_stats

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────────────────────────────────────────
# UsageCaller — quem está a chamar e que app_id lhe pertence
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UsageCaller:
    is_admin: bool
    app_id: str | None   # None = admin (sem filtro de app)


async def get_usage_caller(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ] = None,
    x_admin_secret: Annotated[str | None, Header()] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> UsageCaller:
    """
    Dependency que aceita duas formas de autenticação:

    1. X-Admin-Secret  → admin, vê tudo sem filtros
    2. Bearer <key>    → app, só vê os seus próprios logs

    Se nenhuma for fornecida → 401.
    """
    # Tenta admin primeiro
    if x_admin_secret:
        if x_admin_secret == settings.admin_secret:
            return UsageCaller(is_admin=True, app_id=None)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "invalid_admin_secret", "message": "Invalid admin secret."},
        )

    # Tenta Bearer key
    if credentials and credentials.credentials:
        store = get_key_store()
        entry = await store.validate(credentials.credentials)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_api_key", "message": "Invalid or revoked API key."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return UsageCaller(is_admin=False, app_id=entry.app_id)

    # Nenhuma autenticação
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "missing_authentication",
            "message": (
                "Authenticate with 'Authorization: Bearer <key>' (app) "
                "or 'X-Admin-Secret: <secret>' (admin)."
            ),
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/logs",
    summary="Per-turn usage logs",
    description="""
Lists token consumption records.

**App (Bearer key):** only sees its own rows — `app_id` is enforced automatically.  
**Admin (X-Admin-Secret):** sees everything; can filter by any `app_id`.
    """,
)
async def handle_get_usage_logs(
    caller: Annotated[UsageCaller, Depends(get_usage_caller)],
    company_id: str | None = Query(default=None, description="Filter by company"),
    app_id:     str | None = Query(default=None, description="Filter by app (admin only)"),
    session_id: str | None = Query(default=None, description="Filter by session"),
    date_from:  str | None = Query(default=None, description="ISO 8601, e.g. 2025-03-01"),
    date_to:    str | None = Query(default=None, description="ISO 8601, e.g. 2025-03-31"),
    limit:      int        = Query(default=50, ge=1, le=500),
    offset:     int        = Query(default=0, ge=0),
):
    # App → ignora o app_id do query param e força o seu próprio
    # Admin → usa o app_id do query param (ou None = tudo)
    effective_app_id = caller.app_id if not caller.is_admin else app_id

    return await get_usage_logs(
        company_id=company_id,
        app_id=effective_app_id,
        session_id=session_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/stats",
    summary="Aggregated usage statistics",
    description="""
Total tokens and USD cost with breakdown by model and app.

**App (Bearer key):** only sees its own statistics.  
**Admin (X-Admin-Secret):** sees everything; can filter by any `app_id`.
    """,
)
async def handle_get_usage_stats(
    caller: Annotated[UsageCaller, Depends(get_usage_caller)],
    company_id: str | None = Query(default=None, description="Filter by company"),
    app_id:     str | None = Query(default=None, description="Filter by app (admin only)"),
    date_from:  str | None = Query(default=None, description="ISO 8601"),
    date_to:    str | None = Query(default=None, description="ISO 8601"),
):
    effective_app_id = caller.app_id if not caller.is_admin else app_id

    return await get_usage_stats(
        company_id=company_id,
        app_id=effective_app_id,
        date_from=date_from,
        date_to=date_to,
    )