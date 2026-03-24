"""
Persistência do snapshot de créditos OpenRouter (tabela openrouter_credits_state).
Actualizado apenas quando o admin chama GET /usage/openrouter/credits.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from src.gateway.config import Settings
from src.gateway.key_store import get_key_store
from src.gateway.openrouter_credits import fetch_openrouter_credits

logger = logging.getLogger(__name__)


def _pool():
    return get_key_store()._pool


async def read_remaining_usd_snapshot() -> Optional[float]:
    """
    Último remaining_usd gravado em openrouter_credits_state (sem chamar a API OpenRouter).
    None se a tabela não existir, não houver linha, ou erro de BD.
    """
    pool = _pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT remaining_usd FROM openrouter_credits_state WHERE id = 1"
            )
    except asyncpg.UndefinedTableError:
        return None
    except Exception as e:
        logger.debug("[openrouter_credits_state] read_remaining_usd_snapshot: %s", e)
        return None
    if row is None:
        return None
    return float(row["remaining_usd"] or 0)


async def _read_row() -> Optional[dict[str, Any]]:
    pool = _pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT remaining_usd, total_credits_usd, total_usage_usd,
                       show_alert, checked_at, fetch_ok
                FROM openrouter_credits_state
                WHERE id = 1
                """
            )
    except asyncpg.UndefinedTableError:
        logger.warning(
            "Tabela openrouter_credits_state em falta — corre migrations/005_openrouter_credits_state.sql"
        )
        return None
    if row is None:
        return None
    return {
        "remaining_usd":     float(row["remaining_usd"] or 0),
        "total_credits_usd": float(row["total_credits_usd"]) if row["total_credits_usd"] is not None else None,
        "total_usage_usd":   float(row["total_usage_usd"]) if row["total_usage_usd"] is not None else None,
        "show_alert":        bool(row["show_alert"]),
        "checked_at":        row["checked_at"],
        "fetch_ok":          bool(row["fetch_ok"]),
    }


async def _upsert(
    *,
    remaining_usd: float,
    total_credits_usd: Optional[float],
    total_usage_usd: Optional[float],
    show_alert: bool,
    fetch_ok: bool,
) -> None:
    pool = _pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO openrouter_credits_state (
                    id, remaining_usd, total_credits_usd, total_usage_usd,
                    show_alert, checked_at, fetch_ok
                )
                VALUES (1, $1, $2, $3, $4, now(), $5)
                ON CONFLICT (id) DO UPDATE SET
                    remaining_usd     = EXCLUDED.remaining_usd,
                    total_credits_usd = EXCLUDED.total_credits_usd,
                    total_usage_usd   = EXCLUDED.total_usage_usd,
                    show_alert        = EXCLUDED.show_alert,
                    checked_at        = now(),
                    fetch_ok          = EXCLUDED.fetch_ok
                """,
                remaining_usd,
                total_credits_usd,
                total_usage_usd,
                show_alert,
                fetch_ok,
            )
    except asyncpg.UndefinedTableError:
        raise RuntimeError(
            "openrouter_credits_state: corre migrations/005_openrouter_credits_state.sql"
        ) from None


def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


async def refresh_openrouter_credits_for_api(settings: Settings) -> dict[str, Any]:
    """
    1) Chama OpenRouter GET /credits uma vez.
    2) Grava na tabela openrouter_credits_state.
    3) show_alert = (remaining_usd <= threshold).

    Se OpenRouter falhar, devolve o último estado da base com openrouter_unavailable=true.
    """
    threshold = float(settings.openrouter_credits_alert_threshold_usd)
    snap = await fetch_openrouter_credits(settings)

    if snap is not None:
        remaining = float(snap["remaining"])
        total_c = float(snap["total_credits"])
        total_u = float(snap["total_usage"])
        show_alert = remaining <= threshold
        try:
            await _upsert(
                remaining_usd=remaining,
                total_credits_usd=total_c,
                total_usage_usd=total_u,
                show_alert=show_alert,
                fetch_ok=True,
            )
        except RuntimeError as e:
            logger.error("%s", e)
            return {
                "remaining_usd":       remaining,
                "total_credits_usd":   total_c,
                "total_usage_usd":     total_u,
                "show_alert":          show_alert,
                "alert_threshold_usd": threshold,
                "checked_at":          _iso(datetime.now(timezone.utc)),
                "openrouter_unavailable": False,
                "persisted":           False,
                "persist_error":       str(e),
            }
        except Exception as e:
            logger.exception("[openrouter_credits_state] upsert falhou: %s", e)
            return {
                "remaining_usd":       remaining,
                "total_credits_usd":   total_c,
                "total_usage_usd":     total_u,
                "show_alert":          show_alert,
                "alert_threshold_usd": threshold,
                "checked_at":          _iso(datetime.now(timezone.utc)),
                "openrouter_unavailable": False,
                "persisted":           False,
                "persist_error":       str(e),
            }
        return {
            "remaining_usd":       remaining,
            "total_credits_usd":   total_c,
            "total_usage_usd":     total_u,
            "show_alert":          show_alert,
            "alert_threshold_usd": threshold,
            "checked_at":          _iso(datetime.now(timezone.utc)),
            "openrouter_unavailable": False,
        }

    stale = await _read_row()
    if stale is None:
        return {
            "remaining_usd":          None,
            "total_credits_usd":      None,
            "total_usage_usd":        None,
            "show_alert":             False,
            "alert_threshold_usd":    threshold,
            "checked_at":             None,
            "openrouter_unavailable": True,
        }

    return {
        "remaining_usd":       stale["remaining_usd"],
        "total_credits_usd":   stale["total_credits_usd"],
        "total_usage_usd":     stale["total_usage_usd"],
        "show_alert":          stale["show_alert"],
        "alert_threshold_usd": threshold,
        "checked_at":          _iso(stale["checked_at"]),
        "openrouter_unavailable": True,
        "stale":               True,
    }
