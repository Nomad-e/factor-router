"""
src/gateway/context.py

Modelo Pydantic que representa o contexto obrigatório de cada request ao gateway.
Todos os headers X-* são obrigatórios. Se o valor for desconhecido, o agente envia
a string literal "null". Header ausente = 400. Header com "null" = aceite.

Regra: tokens são dinheiro. Sem contexto completo, sem chamada.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Header, HTTPException, status


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require(value: str | None, header_name: str) -> str:
    """Garante que o header existe. Ausente = 400 explícito."""
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "missing_required_header",
                "header": header_name,
                "message": (
                    f"The '{header_name}' header is required. "
                    f"If the value is unknown, send the literal string \"null\"."
                ),
            },
        )
    return value


def _nullable(value: str | None, header_name: str) -> str | None:
    """
    Header obrigatório mas cujo valor pode ser desconhecido.
    - Ausente       → 400 (erro de programação no agente)
    - Valor "null"  → None (gravado como NULL no DB, aceite)
    - Outro valor   → devolve o valor
    """
    raw = _require(value, header_name)
    return None if raw.lower() == "null" else raw


def _validate_uuid(value: str, header_name: str) -> str:
    """Valida que o valor é um UUID v4 válido."""
    try:
        uuid.UUID(value, version=4)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_header_format",
                "header": header_name,
                "message": (
                    f"The '{header_name}' header must be a valid UUID v4. "
                    f"Received: '{value}'"
                ),
            },
        )
    return value


# ─────────────────────────────────────────────────────────────────────────────
# GatewayContext — injetado como FastAPI Dependency em todos os endpoints
# ─────────────────────────────────────────────────────────────────────────────

class GatewayContext:
    """
    Contexto completo de um request ao gateway.
    Extraído e validado dos headers X-* antes de qualquer processamento.

    Injetar com:
        async def endpoint(ctx: Annotated[GatewayContext, Depends(GatewayContext.from_headers)]):
    """

    def __init__(
        self,
        app_id: str,
        turn_id: str,
        session_id: str,
        conversation_id: str | None,
        user_message: str,
        user_id: str | None,
        user_name: str | None,
        user_email: str | None,
        company_id: str | None,
        company_name: str | None,
    ) -> None:
        self.app_id = app_id
        self.turn_id = turn_id
        self.session_id = session_id
        self.conversation_id = conversation_id
        self.user_message = user_message
        self.user_id = user_id
        self.user_name = user_name
        self.user_email = user_email
        self.company_id = company_id
        self.company_name = company_name

    @classmethod
    async def from_headers(
        cls,
        # ── obrigatórios — nunca null ──────────────────────────────────────
        x_app_id: Annotated[str | None, Header()] = None,
        x_turn_id: Annotated[str | None, Header()] = None,
        x_session_id: Annotated[str | None, Header()] = None,
        x_user_message: Annotated[str | None, Header()] = None,
        # ── obrigatórios — podem ser "null" ───────────────────────────────
        x_conversation_id: Annotated[str | None, Header()] = None,
        x_user_id: Annotated[str | None, Header()] = None,
        x_user_name: Annotated[str | None, Header()] = None,
        x_user_email: Annotated[str | None, Header()] = None,
        x_company_id: Annotated[str | None, Header()] = None,
        x_company_name: Annotated[str | None, Header()] = None,
    ) -> "GatewayContext":

        # Valida presença dos obrigatórios absolutos
        app_id      = _require(x_app_id,      "X-App-Id")
        raw_turn_id = _require(x_turn_id,      "X-Turn-Id")
        session_id  = _require(x_session_id,   "X-Session-Id")
        user_msg    = _require(x_user_message, "X-User-Message")

        # Valida formato do Turn-Id
        turn_id = _validate_uuid(raw_turn_id, "X-Turn-Id")

        # Valida presença dos obrigatórios que aceitam "null"
        conversation_id = _nullable(x_conversation_id, "X-Conversation-Id")
        user_id         = _nullable(x_user_id,         "X-User-Id")
        user_name       = _nullable(x_user_name,       "X-User-Name")
        user_email      = _nullable(x_user_email,      "X-User-Email")
        company_id      = _nullable(x_company_id,      "X-Company-Id")
        company_name    = _nullable(x_company_name,    "X-Company-Name")

        # Trunca a mensagem do utilizador (max 300 chars para o log)
        user_message_preview = user_msg[:300]

        return cls(
            app_id=app_id,
            turn_id=turn_id,
            session_id=session_id,
            conversation_id=conversation_id,
            user_message=user_message_preview,
            user_id=user_id,
            user_name=user_name,
            user_email=user_email,
            company_id=company_id,
            company_name=company_name,
        )

    def __repr__(self) -> str:
        return (
            f"GatewayContext("
            f"app_id={self.app_id!r}, "
            f"turn_id={self.turn_id!r}, "
            f"session_id={self.session_id!r}, "
            f"company_id={self.company_id!r}"
            f")"
        )