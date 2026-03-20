"""
Factor AI ERP Agent — LLM Router (part of llm_orchestrator)
-------------------------------------------------------------
Escolhe o modelo LLM por: complexidade da tarefa, custo, janela de contexto e
estimativa de tokens. O classificador local (Ollama) recebe uma tabela com
tier, contexto, preço e estimativa do pedido para escolher o modelo mais eficiente.

Princípios do router (em mente em cada decisão):
  - Custo        — preço por 1M tokens (input/output) em models_config.yaml
  - Janela       — context_window do modelo deve caber o pedido estimado
  - Tokens       — estimativa input+output a partir da mensagem do utilizador
  - Complexidade — tier (light → heavy) conforme sinais da mensagem

O classificador recebe sempre o YAML completo (description, best_for, context, cost)
via classifier_prompt — decisão com base em description e best_for (sinal).
Flow:
    user_message
        → estimate_request_tokens(user_message)
        → build prompt from full models_config (description, best_for, context, cost)
        → call classifier (Ollama) → {"model": "provider/model-id"}
        → return RouterResult (model_id, tokens, estimativa, conclusão)
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import yaml

from dotenv import load_dotenv

from src.router.classifier_prompt import build_classifier_prompt
from src.router.router_logs import log_router_decision

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Router result (tokens + how the classifier decided)
# ---------------------------------------------------------------------------

@dataclass
class RouterResult:
    """Resultado do router: modelo, tokens do classificador, estimativa do pedido e conclusão."""
    model_id: str
    input_tokens: int
    output_tokens: int
    raw_response: str
    eval_duration_ms: Optional[float] = None
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0

    def __str__(self) -> str:
        return self.model_id

    @property
    def estimated_total_tokens(self) -> int:
        return self.estimated_input_tokens + self.estimated_output_tokens

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
CLASSIFIER_MODEL   = os.getenv("CLASSIFIER_MODEL", "qwen3.5:4b")
CLASSIFIER_TIMEOUT = float(os.getenv("CLASSIFIER_TIMEOUT_SECONDS", "6.0"))  # YAML completo = prompt maior
# Classificador usa sempre o YAML completo (models_config.yaml): description, best_for (sinal).

CONFIG_PATH = Path(__file__).parent / "models_config.yaml"


# ---------------------------------------------------------------------------
# Config Loader (cached at module level — loaded once on startup)
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"models_config.yaml not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_CONFIG: dict       = _load_config()
_MODELS: list[dict] = _CONFIG["models"]
_DEFAULT_MODEL: str = _CONFIG["default_model"]


# ---------------------------------------------------------------------------
# Token estimation & pricing (for efficiency: cost, context, tokens)
# ---------------------------------------------------------------------------

# Base context assumido para o pedido ao LLM principal (system + history + esta mensagem)
_ESTIMATED_SYSTEM_AND_CONTEXT_TOKENS = 3500
_ESTIMATED_OUTPUT_BASE_TOKENS = 400
# Fator aproximado: chars -> tokens (conservador)
_CHARS_PER_TOKEN = 3.5


def _parse_price(value: str | int | float) -> float:
    """Converte preço do YAML (e.g. '$1.00', '€0.50') para float."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    for prefix in ("$", "€", "£", "¥", " "):
        s = s.replace(prefix, "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def estimate_request_tokens(user_message: str) -> tuple[int, int]:
    """
    Estima tokens que o modelo principal irá usar para este pedido (input + output).
    Usado pelo router para: ver se cabe na janela do modelo e estimar custo.

    - Input: contexto base (system + histórico) + mensagem do utilizador.
    - Output: base + proporcional ao tamanho do pedido (respostas longas para pedidos longos).
    """
    if not user_message or not user_message.strip():
        return _ESTIMATED_SYSTEM_AND_CONTEXT_TOKENS, _ESTIMATED_OUTPUT_BASE_TOKENS
    msg_len = len(user_message.strip())
    msg_tokens = max(1, int(msg_len / _CHARS_PER_TOKEN))
    input_est = _ESTIMATED_SYSTEM_AND_CONTEXT_TOKENS + msg_tokens
    output_est = _ESTIMATED_OUTPUT_BASE_TOKENS + int(msg_tokens * 1.2)  # resposta ~ proporcional
    return input_est, output_est


def get_model_info(model_id: str) -> Optional[dict]:
    """
    Devolve contexto e custo para um model_id (para eficiência: janela, preço por 1M).
    Útil para filtrar por context_window >= estimated_tokens ou estimar custo do pedido.
    """
    for m in _MODELS:
        if m.get("id") == model_id:
            pricing = m.get("pricing") or {}
            return {
                "id": model_id,
                "tier": m.get("tier"),
                "context_window": m.get("context_window") or 0,
                "input_per_1m_tokens": _parse_price(pricing.get("input_per_1m_tokens", 0)),
                "output_per_1m_tokens": _parse_price(pricing.get("output_per_1m_tokens", 0)),
            }
    return None


# ---------------------------------------------------------------------------
# Full config prompt (YAML completo) — modo default
# ---------------------------------------------------------------------------
# O classificador recebe descrições completas, best_for e custo/contexto de cada
# modelo para decidir com base em toda a informação — não só keywords/sinais.
# ---------------------------------------------------------------------------

def _build_full_prompt(
    user_message: str,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
) -> tuple[str, str]:
    """
    Constrói o prompt do classificador a partir do models_config completo.
    Inclui DESCRIPTION, BEST FOR (exemplos), CONTEXT e COST por modelo,
    mais estimativa de tokens do pedido para decisão informada.
    """
    system, user = build_classifier_prompt(user_message, _MODELS, _DEFAULT_MODEL)
    total_est = estimated_input_tokens + estimated_output_tokens
    user = (
        user.rstrip()
        + f"\n\nEstimated tokens for this request: input ~{estimated_input_tokens}, output ~{estimated_output_tokens}, total ~{total_est}. "
        "Consider each model's context window and cost when choosing. Reply with JSON only: {\"model\": \"provider/model-id\"}"
    )
    return system, user


# ---------------------------------------------------------------------------
# Classifier call
# ---------------------------------------------------------------------------

def _extract_usage(data: dict) -> tuple[int, int, Optional[float]]:
    """
    Extrai uso de tokens da resposta Ollama.
    Campos: prompt_eval_count (input), eval_count (output), eval_duration (nanosegundos).
    """
    inp = data.get("prompt_eval_count")
    out = data.get("eval_count")
    duration_ns = data.get("eval_duration")
    inp = int(inp) if inp is not None else 0
    out = int(out) if out is not None else 0
    duration_ms = (float(duration_ns) / 1e6) if duration_ns is not None else None
    return inp, out, duration_ms


async def _call_classifier(
    user_message: str,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
) -> tuple[str, int, int, Optional[float]]:
    """
    Envia o prompt ao classificador (Ollama) com estimativa de tokens.
    Returns:
        (content, input_tokens, output_tokens, eval_duration_ms)
    """
    system_prompt, user_prompt = _build_full_prompt(
        user_message, estimated_input_tokens, estimated_output_tokens
    )

    payload = {
        "model": CLASSIFIER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 128,
        },
    }

    async with httpx.AsyncClient(timeout=CLASSIFIER_TIMEOUT) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    content = (data.get("message") or {}).get("content") or ""
    inp, out, duration_ms = _extract_usage(data)
    return content.strip(), inp, out, duration_ms


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_model_from_response(raw: str) -> tuple[str, Optional[str]]:
    """
    Parses JSON response from classifier and returns (model_id, fallback_reason).
    fallback_reason is None on success; "unknown_model" or "parse_error" on fallback.
    """
    valid_ids = {m["id"] for m in _MODELS}

    try:
        clean = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        if start != -1 and end > start:
            clean = clean[start:end]

        parsed   = json.loads(clean)
        model_id = (parsed.get("model") or "").strip()

        if model_id in valid_ids:
            return model_id, None

        logger.warning(
            f"[Router] Unknown model '{model_id}' — "
            f"falling back to: {_DEFAULT_MODEL}"
        )
        return _DEFAULT_MODEL, "unknown_model"

    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        logger.warning(
            f"[Router] Parse failed: '{raw}' — {e}. "
            f"Falling back to: {_DEFAULT_MODEL}"
        )
        return _DEFAULT_MODEL, "parse_error"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def route(user_message: str) -> RouterResult:
    """
    Dado a mensagem do utilizador, devolve o modelo a usar e metadados do classificador.

    Sempre devolve um resultado válido (model_id preenchido). Em falha usa default_model.
    Inclui tokens gastos (input/output) e a resposta bruta do classificador (como chegou à conclusão).

    Args:
        user_message: Mensagem do utilizador (último turno).

    Returns:
        RouterResult com model_id, input_tokens, output_tokens, raw_response, eval_duration_ms.
    """
    if not user_message or not user_message.strip():
        logger.debug("[Router] Empty message — using default model.")
        print(f"[LLMRouter] model: {_DEFAULT_MODEL}")
        _model_info = get_model_info(_DEFAULT_MODEL) or {}
        await log_router_decision(
            user_message=user_message or "",
            model_id=_DEFAULT_MODEL,
            fallback_reason="empty_message",
            model_tier=_model_info.get("tier"),
            model_context_window=_model_info.get("context_window"),
            model_input_price_per_1m=_model_info.get("input_per_1m_tokens"),
            model_output_price_per_1m=_model_info.get("output_per_1m_tokens"),
        )
        return RouterResult(
            model_id=_DEFAULT_MODEL,
            input_tokens=0,
            output_tokens=0,
            raw_response="(empty message → default)",
            estimated_input_tokens=0,
            estimated_output_tokens=0,
        )

    est_in, est_out = estimate_request_tokens(user_message)

    try:
        content, inp, out, duration_ms = await _call_classifier(
            user_message, est_in, est_out
        )
        model_id, parse_fallback = _parse_model_from_response(content)
        _model_info = get_model_info(model_id) or {}
        await log_router_decision(
            user_message=user_message,
            model_id=model_id,
            fallback_reason=parse_fallback,
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
            classifier_input_tokens=inp,
            classifier_output_tokens=out,
            eval_duration_ms=duration_ms,
            raw_response=content,
            model_tier=_model_info.get("tier"),
            model_context_window=_model_info.get("context_window"),
            model_input_price_per_1m=_model_info.get("input_per_1m_tokens"),
            model_output_price_per_1m=_model_info.get("output_per_1m_tokens"),
        )
        result = RouterResult(
            model_id=model_id,
            input_tokens=inp,
            output_tokens=out,
            raw_response=content,
            eval_duration_ms=duration_ms,
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
        )
        logger.info(
            f"[Router] '{user_message[:60]}' → {model_id} "
            f"(est ~{est_in + est_out} tok, in={inp} out={out} clf, {duration_ms or '?'}ms)"
        )
        print(f"[LLMRouter] model: {model_id}")
        return result
    except httpx.TimeoutException:
        logger.warning(
            f"[Router] Classifier timeout ({CLASSIFIER_TIMEOUT}s) — "
            f"falling back to: {_DEFAULT_MODEL}"
        )
        print(f"[LLMRouter] model: {_DEFAULT_MODEL}")
        _model_info = get_model_info(_DEFAULT_MODEL) or {}
        await log_router_decision(
            user_message=user_message,
            model_id=_DEFAULT_MODEL,
            fallback_reason="timeout",
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
            raw_response="(timeout)",
            model_tier=_model_info.get("tier"),
            model_context_window=_model_info.get("context_window"),
            model_input_price_per_1m=_model_info.get("input_per_1m_tokens"),
            model_output_price_per_1m=_model_info.get("output_per_1m_tokens"),
        )
        return RouterResult(
            model_id=_DEFAULT_MODEL,
            input_tokens=0,
            output_tokens=0,
            raw_response="(timeout)",
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
        )
    except Exception as e:
        logger.error(
            f"[Router] Unexpected error: {e} — "
            f"falling back to: {_DEFAULT_MODEL}"
        )
        print(f"[LLMRouter] model: {_DEFAULT_MODEL}")
        _model_info = get_model_info(_DEFAULT_MODEL) or {}
        await log_router_decision(
            user_message=user_message,
            model_id=_DEFAULT_MODEL,
            fallback_reason=f"error:{type(e).__name__}",
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
            raw_response=f"(error: {e})",
            model_tier=_model_info.get("tier"),
            model_context_window=_model_info.get("context_window"),
            model_input_price_per_1m=_model_info.get("input_per_1m_tokens"),
            model_output_price_per_1m=_model_info.get("output_per_1m_tokens"),
        )
        return RouterResult(
            model_id=_DEFAULT_MODEL,
            input_tokens=0,
            output_tokens=0,
            raw_response=f"(error: {e})",
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
        )