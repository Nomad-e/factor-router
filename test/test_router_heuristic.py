"""Testes do router LLM puro (sem heurísticas, sem modo híbrido)."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.router import router as router_mod
from src.router.router import route, _DEFAULT_MODEL


class TestRouterPureLLM(unittest.TestCase):
    """Testes para o router LLM puro — sem heurísticas, sem keywords."""

    def test_default_model_is_factorai(self) -> None:
        """O default model deve ser o FactorAI vLLM local."""
        self.assertIn("factorai", _DEFAULT_MODEL.lower())

    def test_empty_message_returns_default(self) -> None:
        """Mensagem vazia retorna default_model."""
        result = asyncio.run(route(""))
        self.assertEqual(result.model_id, _DEFAULT_MODEL)

    def test_tool_choice_required_forces_gpt41mini(self) -> None:
        """tool_choice='required' força openai/gpt-4.1-mini."""
        async def run() -> str:
            with patch.object(
                router_mod,
                "_call_classifier",
                new=AsyncMock(
                    return_value=('{ "model": "qwen/qwen3.6-plus" }', 10, 4, 1.0)
                ),
            ):
                with patch.object(router_mod, "OLLAMA_BASE_URL", "http://localhost:11434"):
                    rr = await route(
                        "find customer and create invoice",
                        tool_choice="required",
                    )
                    return rr.model_id

        self.assertEqual(asyncio.run(run()), "openai/gpt-4.1-mini")

    def test_classifier_success_returns_model(self) -> None:
        """Classificador com sucesso retorna o modelo escolhido."""
        async def run() -> str:
            with patch.object(
                router_mod,
                "_call_classifier",
                new=AsyncMock(
                    return_value=('{ "model": "qwen/qwen3.6-plus" }', 10, 4, 1.0)
                ),
            ):
                with patch.object(router_mod, "OLLAMA_BASE_URL", "http://localhost:11434"):
                    rr = await route("please fix this python bug and refactor the endpoint")
                    return rr.model_id

        self.assertEqual(asyncio.run(run()), "qwen/qwen3.6-plus")

    def test_classifier_timeout_falls_back_to_default(self) -> None:
        """Timeout do classificador faz fallback para default_model."""
        async def run() -> str:
            with patch.object(
                router_mod,
                "_call_classifier",
                new=AsyncMock(side_effect=router_mod.httpx.TimeoutException("timeout")),
            ):
                with patch.object(router_mod, "OLLAMA_BASE_URL", "http://localhost:11434"):
                    rr = await route("please fix this python bug and refactor the endpoint")
                    return rr.model_id

        self.assertEqual(asyncio.run(run()), _DEFAULT_MODEL)

    def test_classifier_parse_error_falls_back_to_default(self) -> None:
        """Resposta não-JSON do classificador faz fallback para default_model."""
        async def run() -> str:
            with patch.object(
                router_mod,
                "_call_classifier",
                new=AsyncMock(return_value=("not-json", 10, 4, 1.0)),
            ):
                with patch.object(router_mod, "OLLAMA_BASE_URL", "http://localhost:11434"):
                    rr = await route("please fix this python bug and refactor the endpoint")
                    return rr.model_id

        self.assertEqual(asyncio.run(run()), _DEFAULT_MODEL)

    def test_classifier_unknown_model_falls_back_to_default(self) -> None:
        """Modelo desconhecido no classificador faz fallback para default_model."""
        async def run() -> str:
            with patch.object(
                router_mod,
                "_call_classifier",
                new=AsyncMock(
                    return_value=('{ "model": "nonexistent/model" }', 10, 4, 1.0)
                ),
            ):
                with patch.object(router_mod, "OLLAMA_BASE_URL", "http://localhost:11434"):
                    rr = await route("please fix this python bug and refactor the endpoint")
                    return rr.model_id

        self.assertEqual(asyncio.run(run()), _DEFAULT_MODEL)

    def test_no_ollama_falls_back_to_default(self) -> None:
        """Sem OLLAMA_BASE_URL definido, faz fallback para default_model."""
        async def run() -> str:
            with patch.object(router_mod, "OLLAMA_BASE_URL", ""):
                rr = await route("test message")
                return rr.model_id

        self.assertEqual(asyncio.run(run()), _DEFAULT_MODEL)

    def test_router_result_str(self) -> None:
        """RouterResult.__str__ retorna model_id."""
        result = router_mod.RouterResult(
            model_id="test/model", input_tokens=10, output_tokens=5, raw_response="ok"
        )
        self.assertEqual(str(result), "test/model")

    def test_router_result_estimated_total_tokens(self) -> None:
        """RouterResult.estimated_total_tokens soma input + output."""
        result = router_mod.RouterResult(
            model_id="test/model",
            input_tokens=100,
            output_tokens=50,
            raw_response="ok",
            estimated_input_tokens=120,
            estimated_output_tokens=60,
        )
        self.assertEqual(result.estimated_total_tokens, 180)


if __name__ == "__main__":
    unittest.main()
