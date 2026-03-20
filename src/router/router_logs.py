"""
Hooks de logging das decisões do router.

Stub: no-op até existir persistência (DB, fila, etc.).
"""
from __future__ import annotations

from typing import Any


async def log_router_decision(**kwargs: Any) -> None:
    """Regista uma decisão do router; por agora não faz nada."""
    del kwargs  # reservado para implementação futura
