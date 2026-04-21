"""
Testes do provider FactorAI vLLM.

Valida:
  1. Resolução de provider — factorai/qwen3.6-35b-a3b resolve para FACTORAI_VLLM_BASE_URL
  2. Modelo no YAML — modelo registado com pricing $0
  3. Fallback — modelo FactorAI está na fallback chain do router
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import yaml

# ---------------------------------------------------------------------------
# 1. Testes de resolução de provider (src/gateway/provider_upstream.py)
# ---------------------------------------------------------------------------

class TestProviderResolution(unittest.TestCase):
    """resolve_upstream deve mapear factorai/<name> para FACTORAI_VLLM_BASE_URL."""

    def _make_settings(self, factorai_url: str = "http://192.168.1.223:8000/v1") -> object:
        """Cria um Settings mock com os campos mínimos para resolve_upstream."""
        from types import SimpleNamespace
        return SimpleNamespace(
            factorai_vllm_base_url=factorai_url,
            factorai_vllm_api_key="EMPTY",
            ollama_base_url=None,
            upstream_url="https://openrouter.ai/api/v1",
            openrouter_api_prod="sk-prod-fake",
            openrouter_api_dev="sk-dev-fake",
        )

    def test_factorai_model_resolves_to_vllm_base_url(self) -> None:
        """factorai/qwen3.6-35b-a3b → chat_completions_url usa FACTORAI_VLLM_BASE_URL."""
        from src.gateway.provider_upstream import resolve_upstream

        settings = self._make_settings("http://192.168.1.223:8000/v1")
        target = resolve_upstream("factorai/qwen3.6-35b-a3b", settings)

        self.assertEqual(target.chat_completions_url, "http://192.168.1.223:8000/v1/chat/completions")
        self.assertEqual(target.api_model, "qwen3.6-35b-a3b")
        self.assertEqual(target.selected_env, "factorai")
        self.assertEqual(target.api_key_source, "FACTORAI_VLLM_API_KEY")

    def test_factorai_strips_trailing_slash(self) -> None:
        """Base URL com trailing slash é normalizado correctamente."""
        from src.gateway.provider_upstream import resolve_upstream

        settings = self._make_settings("http://192.168.1.223:8000/v1/")
        target = resolve_upstream("factorai/qwen3.6-35b-a3b", settings)

        self.assertEqual(target.chat_completions_url, "http://192.168.1.223:8000/v1/chat/completions")

    def test_factorai_missing_base_url_raises_503(self) -> None:
        """Sem FACTORAI_VLLM_BASE_URL → HTTPException 503."""
        from fastapi import HTTPException
        from src.gateway.provider_upstream import resolve_upstream

        settings = self._make_settings(factorai_url="")
        with self.assertRaises(HTTPException) as ctx:
            resolve_upstream("factorai/qwen3.6-35b-a3b", settings)

        self.assertEqual(ctx.exception.status_code, 503)
        detail = ctx.exception.detail
        self.assertEqual(detail["error"], "factorai_vllm_not_configured")

    def test_factorai_empty_name_raises_400(self) -> None:
        """factorai/ (sem nome) → HTTPException 400."""
        from fastapi import HTTPException
        from src.gateway.provider_upstream import resolve_upstream

        settings = self._make_settings()
        with self.assertRaises(HTTPException) as ctx:
            resolve_upstream("factorai/", settings)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_factorai_model")

    def test_factorai_api_key_header(self) -> None:
        """Com API key não-EMPTY, o header Authorization é incluído."""
        from src.gateway.provider_upstream import resolve_upstream
        from types import SimpleNamespace

        settings = SimpleNamespace(
            factorai_vllm_base_url="http://192.168.1.223:8000/v1",
            factorai_vllm_api_key="sk-vllm-secret",
            ollama_base_url=None,
            upstream_url="https://openrouter.ai/api/v1",
            openrouter_api_prod="sk-prod-fake",
            openrouter_api_dev="sk-dev-fake",
        )
        target = resolve_upstream("factorai/qwen3.6-35b-a3b", settings)

        self.assertIn("Authorization", target.headers)
        self.assertEqual(target.headers["Authorization"], "Bearer sk-vllm-secret")

    def test_factorai_empty_api_key_no_auth_header(self) -> None:
        """Com API key = 'EMPTY', nenhum header Authorization é enviado."""
        from src.gateway.provider_upstream import resolve_upstream

        settings = self._make_settings()
        target = resolve_upstream("factorai/qwen3.6-35b-a3b", settings)

        self.assertEqual(target.headers, {})


# ---------------------------------------------------------------------------
# 2. Testes do modelo no YAML (src/router/models_config.yaml)
# ---------------------------------------------------------------------------

class TestModelConfigYaml(unittest.TestCase):
    """O modelo factorai/qwen3.6-35b-a3b deve estar registado com pricing $0."""

    @classmethod
    def setUpClass(cls) -> None:
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "router", "models_config.yaml"
        )
        with open(config_path, "r", encoding="utf-8") as f:
            cls.config = yaml.safe_load(f)

    def _find_model(self, model_id: str) -> dict | None:
        for m in self.config["models"]:
            if m.get("id") == model_id:
                return m
        return None

    def test_factorai_model_exists_in_yaml(self) -> None:
        """factorai/qwen3.6-35b-a3b existe em models_config.yaml."""
        model = self._find_model("factorai/qwen3.6-35b-a3b")
        self.assertIsNotNone(model, "Modelo factorai/qwen3.6-35b-a3b não encontrado em models_config.yaml")

    def test_factorai_pricing_is_zero(self) -> None:
        """Pricing do modelo FactorAI é $0 (input e output)."""
        model = self._find_model("factorai/qwen3.6-35b-a3b")
        self.assertIsNotNone(model)

        pricing = model.get("pricing", {})
        input_price = str(pricing.get("input_per_1m_tokens", "")).strip().replace("$", "")
        output_price = str(pricing.get("output_per_1m_tokens", "")).strip().replace("$", "")

        self.assertEqual(float(input_price), 0.0, "Input price deve ser $0")
        self.assertEqual(float(output_price), 0.0, "Output price deve ser $0")

    def test_factorai_tier_is_reasoning(self) -> None:
        """Modelo FactorAI está no tier 'reasoning'."""
        model = self._find_model("factorai/qwen3.6-35b-a3b")
        self.assertIsNotNone(model)
        self.assertEqual(model.get("tier"), "reasoning")

    def test_factorai_is_local(self) -> None:
        """Modelo FactorAI tem is_local = true."""
        model = self._find_model("factorai/qwen3.6-35b-a3b")
        self.assertIsNotNone(model)
        self.assertTrue(model.get("is_local"), "is_local deve ser true")

    def test_factorai_provider_field(self) -> None:
        """Modelo FactorAI tem provider = 'factorai'."""
        model = self._find_model("factorai/qwen3.6-35b-a3b")
        self.assertIsNotNone(model)
        self.assertEqual(model.get("provider"), "factorai")


# ---------------------------------------------------------------------------
# 3. Testes de fallback chain (src/router/router.py)
# ---------------------------------------------------------------------------

class TestFallbackChain(unittest.TestCase):
    """O modelo FactorAI deve estar na fallback chain do router."""

    def test_factorai_in_valid_ids(self) -> None:
        """factorai/qwen3.6-35b-a3b está em _VALID_IDS do router."""
        from src.router.router import _VALID_IDS

        self.assertIn("factorai/qwen3.6-35b-a3b", _VALID_IDS)

    def test_factorai_model_info_returns_pricing(self) -> None:
        """get_model_info devolve pricing $0 para o modelo FactorAI."""
        from src.router.router import get_model_info

        info = get_model_info("factorai/qwen3.6-35b-a3b")
        self.assertIsNotNone(info, "get_model_info deve encontrar o modelo FactorAI")
        self.assertEqual(info["input_per_1m_tokens"], 0.0)
        self.assertEqual(info["output_per_1m_tokens"], 0.0)
        self.assertEqual(info["tier"], "reasoning")

    def test_router_fallback_when_ollama_unset(self) -> None:
        """Quando OLLAMA_BASE_URL não está definido, o router faz fallback
        para o modelo heurístico — que pode ser FactorAI dependendo do input."""
        import asyncio
        from unittest.mock import patch
        from src.router import router as router_mod
        from src.router.router import route

        async def run() -> str:
            with patch.object(router_mod, "ROUTER_DECISION_MODE", "hybrid"):
                with patch.object(router_mod, "OLLAMA_BASE_URL", ""):
                    rr = await route("run a simple python code test")
                    return rr.model_id

        model_id = asyncio.run(run())
        # O fallback heurístico para código é qwen/qwen3.6-plus, mas o router
        # não deve crashar — prova que a fallback chain funciona.
        self.assertIn(model_id, router_mod._VALID_IDS)

    def test_factorai_resolved_via_provider_upstream_in_proxy(self) -> None:
        """body_for_upstream_proxy ajusta o model field correctamente para FactorAI."""
        from src.gateway.provider_upstream import resolve_upstream, body_for_upstream_proxy
        from types import SimpleNamespace

        settings = SimpleNamespace(
            factorai_vllm_base_url="http://192.168.1.223:8000/v1",
            factorai_vllm_api_key="EMPTY",
            ollama_base_url=None,
            upstream_url="https://openrouter.ai/api/v1",
            openrouter_api_prod="sk-prod-fake",
            openrouter_api_dev="sk-dev-fake",
        )
        target = resolve_upstream("factorai/qwen3.6-35b-a3b", settings)
        body = {
            "model": "factorai/qwen3.6-35b-a3b",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        proxied = body_for_upstream_proxy(body, target)

        # O model no body enviado ao upstream deve ser o nome curto (sem prefixo)
        self.assertEqual(proxied["model"], "qwen3.6-35b-a3b")
        # stream=True mantém stream_options
        self.assertIn("stream_options", proxied)

        # stream=False remove stream_options
        body_no_stream = {**body, "stream": False}
        proxied_no_stream = body_for_upstream_proxy(body_no_stream, target)
        self.assertNotIn("stream_options", proxied_no_stream)


if __name__ == "__main__":
    unittest.main()
