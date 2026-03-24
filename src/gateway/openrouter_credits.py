"""
Cliente HTTP para GET /api/v1/credits no OpenRouter.

Pode ser necessária uma *management API key*; se a key de chat devolver 403,
define OPENROUTER_MANAGEMENT_API_KEY no .env. Não é obrigatório criar outra key
se a que tens já tiver permissão para /credits.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from src.gateway.config import Settings

logger = logging.getLogger(__name__)


def _credits_url(settings: Settings) -> str:
    return f"{settings.upstream_url.rstrip('/')}/credits"


def _auth_key(settings: Settings) -> str:
    return (settings.openrouter_management_api_key or settings.openrouter_api_key or "").strip()


async def fetch_openrouter_credits(settings: Settings) -> Optional[dict[str, Any]]:
    """
    Devolve {"total_credits", "total_usage", "remaining"} ou None se indisponível.
    remaining = total_credits - total_usage (USD).
    """
    key = _auth_key(settings)
    if not key:
        return None
    url = _credits_url(settings)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                url,
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.RequestError as e:
        logger.warning("[OpenRouter/credits] pedido falhou: %s", e)
        return None

    if r.status_code == 403:
        logger.warning(
            "[OpenRouter/credits] 403 Forbidden — a key pode não ter permissão de gestão. "
            "Cria uma management key no OpenRouter e define OPENROUTER_MANAGEMENT_API_KEY."
        )
        return None
    if r.status_code != 200:
        logger.warning(
            "[OpenRouter/credits] HTTP %s: %s",
            r.status_code,
            (r.text or "")[:300],
        )
        return None

    try:
        payload = r.json()
    except json.JSONDecodeError:
        return None
    data = payload.get("data") or {}
    try:
        total = float(data.get("total_credits") or 0)
        used = float(data.get("total_usage") or 0)
    except (TypeError, ValueError):
        return None
    remaining = max(0.0, total - used)
    return {
        "total_credits": total,
        "total_usage": used,
        "remaining": remaining,
    }
