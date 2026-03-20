"""
src/api/routes/usage.py

Endpoints de leitura do centro de custos.
GET /usage/logs   — lista de registos por turno
GET /usage/stats  — agregados por modelo, empresa e app
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.gateway.auth import AuthenticatedApp, authenticate
from src.usage.service import get_usage_logs, get_usage_stats

router = APIRouter()


@router.get(
    "/logs",
    summary="Per-turn usage logs",
    description="Lists token consumption records. Filterable by company, app, session, and date.",
)
async def handle_get_usage_logs(
    auth: Annotated[AuthenticatedApp, Depends(authenticate)],
    company_id: str | None = Query(default=None,  description="Filter by company"),
    app_id:     str | None = Query(default=None,  description="Filter by app"),
    session_id: str | None = Query(default=None,  description="Filter by session"),
    date_from:  str | None = Query(default=None,  description="ISO 8601, e.g. 2025-03-01"),
    date_to:    str | None = Query(default=None,  description="ISO 8601, e.g. 2025-03-31"),
    limit:      int        = Query(default=50, ge=1, le=500),
    offset:     int        = Query(default=0,  ge=0),
):
    return await get_usage_logs(
        company_id=company_id,
        app_id=app_id,
        session_id=session_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/stats",
    summary="Aggregated usage statistics",
    description="Total tokens and USD cost with breakdown by model and app.",
)
async def handle_get_usage_stats(
    auth: Annotated[AuthenticatedApp, Depends(authenticate)],
    company_id: str | None = Query(default=None, description="Filter by company"),
    app_id:     str | None = Query(default=None, description="Filter by app"),
    date_from:  str | None = Query(default=None, description="ISO 8601"),
    date_to:    str | None = Query(default=None, description="ISO 8601"),
):
    return await get_usage_stats(
        company_id=company_id,
        app_id=app_id,
        date_from=date_from,
        date_to=date_to,
    )