"""
src/api/routes/proxy.py

Rota FastAPI — POST /v1/chat/completions.
Delega a lógica em src.gateway.proxy.handle_chat_completions.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from src.gateway.auth import AuthenticatedApp, authenticate
from src.gateway.config import Settings, get_settings
from src.gateway.context import GatewayContext
from src.gateway.proxy import handle_chat_completions

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/chat/completions",
    summary="Chat completions (OpenAI-compatible)",
    description="""
Main gateway endpoint. Accepts the same body the OpenAI SDK sends.

**The `model` field in the body is ignored** — the gateway uses an internal router to
pick the most suitable and cost-effective model for each request.

Supports `stream: true` (SSE) and `stream: false` (full JSON).

Requires all `X-*` headers documented in the API description.
    """,
    tags=["proxy"],
)
async def chat_completions(
    request: Request,
    auth: Annotated[AuthenticatedApp, Depends(authenticate)],
    ctx: Annotated[GatewayContext, Depends(GatewayContext.from_headers)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Proxy transparente para o OpenRouter com routing automático de modelos.

    O app_id vem do auth (API Key) — fonte de verdade.
    O header X-App-Id é apenas para logging; não pode falsificar identidade.
    """
    if ctx.app_id != auth.app_id:
        logger.warning(
            "X-App-Id '%s' does not match the API key (actual app_id: '%s'). "
            "Using the app_id from the API key.",
            ctx.app_id,
            auth.app_id,
        )
        ctx.app_id = auth.app_id

    return await handle_chat_completions(request, ctx, settings)
