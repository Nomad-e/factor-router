#!/usr/bin/env python3
"""
Teste manual do modelo FactorAI via FactorRouter.

Faz um call real ao FactorRouter com model="factorai/qwen3.6-35b-a3b"
e reporta se o endpoint responde correctamente.

Uso:
    python scripts/test-factorai-model.py

Requisitos:
    - O gateway FactorRouter deve estar a correr (default: http://localhost:8003)
    - Uma API key válida deve estar configurada (variável GATEWAY_API_KEY ou --api-key)
    - O modelo factorai/qwen3.6-35b-a3b deve estar servido no vLLM backend
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib.parse import urljoin

try:
    import httpx
except ImportError:
    print("ERRO: httpx não está instalado. Instala com: pip install httpx", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Teste manual do modelo FactorAI via FactorRouter"
    )
    parser.add_argument(
        "--gateway-url",
        default=os.getenv("FACTOR_ROUTER_URL", "http://localhost:8003"),
        help="URL do FactorRouter (default: http://localhost:8003 ou $FACTOR_ROUTER_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("GATEWAY_API_KEY", ""),
        help="API key do gateway (default: $GATEWAY_API_KEY)",
    )
    parser.add_argument(
        "--model",
        default="factorai/qwen3.6-35b-a3b",
        help="Model ID a testar (default: factorai/qwen3.6-35b-a3b)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout em segundos (default: 120)",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Usar streaming (SSE) em vez de resposta completa",
    )
    return parser.parse_args()


def test_non_stream(client: httpx.Client, gateway_url: str, model: str, api_key: str, timeout: int) -> bool:
    """Teste com resposta completa (não-streaming)."""
    url = urljoin(gateway_url, "/v1/chat/completions")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Responde sempre em português."},
            {"role": "user", "content": "Diz apenas 'FactorAI OK' e mais nada."},
        ],
        "max_tokens": 20,
        "temperature": 0.0,
    }

    print(f"\n📡 POST {url}")
    print(f"   model: {model}")
    print(f"   timeout: {timeout}s")
    print()

    start = time.monotonic()
    try:
        response = client.post(url, json=payload, headers=headers, timeout=timeout)
        elapsed = time.monotonic() - start

        print(f"⏱️  Response time: {elapsed:.2f}s")
        print(f"📊 HTTP Status: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ Erro HTTP {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return False

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            print("❌ Sem choices na resposta")
            print(f"   Response: {json.dumps(data, indent=2)[:500]}")
            return False

        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        finish_reason = choice.get("finish_reason", "")

        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)

        print(f"✅ Resposta recebida com sucesso")
        print(f"   finish_reason: {finish_reason}")
        print(f"   content: {content.strip()!r}")
        print(f"   tokens: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")

        # Verificar que o modelo resolvido é o nome curto (sem prefixo factorai/)
        response_model = data.get("model", "")
        if response_model:
            print(f"   resolved model: {response_model}")
            if response_model == "qwen3.6-35b-a3b":
                print(f"   ✅ Modelo resolvido correctamente (prefixo removido)")
            else:
                print(f"   ⚠️  Modelo resolvido inesperado: {response_model}")

        return True

    except httpx.TimeoutException:
        print(f"❌ Timeout após {timeout}s")
        return False
    except httpx.ConnectError as e:
        print(f"❌ Erro de conexão: {e}")
        print(f"   O gateway está a correr em {gateway_url}?")
        return False
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return False


def test_stream(client: httpx.Client, gateway_url: str, model: str, api_key: str, timeout: int) -> bool:
    """Teste com streaming (SSE)."""
    url = urljoin(gateway_url, "/v1/chat/completions")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Responde sempre em português."},
            {"role": "user", "content": "Conta de 1 a 3 em português."},
        ],
        "max_tokens": 30,
        "temperature": 0.0,
        "stream": True,
    }

    print(f"\n📡 POST {url} (streaming)")
    print(f"   model: {model}")
    print(f"   timeout: {timeout}s")
    print()

    start = time.monotonic()
    try:
        with client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as response:
            print(f"📊 HTTP Status: {response.status_code}")

            if response.status_code != 200:
                print(f"❌ Erro HTTP {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return False

            content_parts: list[str] = []
            chunk_count = 0
            for line in response.iter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        delta_content = delta.get("content", "")
                        if delta_content:
                            content_parts.append(delta_content)
                            print(delta_content, end="", flush=True)
                        chunk_count += 1
                except json.JSONDecodeError:
                    continue

            elapsed = time.monotonic() - start
            print()  # newline after streamed content
            print(f"\n⏱️  Total time: {elapsed:.2f}s")
            print(f"📦 Chunks received: {chunk_count}")
            print(f"✅ Content: {''.join(content_parts).strip()!r}")
            return True

    except httpx.TimeoutException:
        print(f"❌ Timeout após {timeout}s")
        return False
    except httpx.ConnectError as e:
        print(f"❌ Erro de conexão: {e}")
        return False
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return False


def main() -> None:
    args = parse_args()

    print("=" * 60)
    print("  FactorAI Model Test — Manual")
    print("=" * 60)
    print(f"  Gateway:  {args.gateway_url}")
    print(f"  Model:    {args.model}")
    print(f"  API Key:  {'***' + args.api_key[-4:] if len(args.api_key) > 4 else '(none)'}")
    print(f"  Stream:   {args.stream}")
    print(f"  Timeout:  {args.timeout}s")
    print("=" * 60)

    headers: dict[str, str] = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    with httpx.Client(headers=headers) as client:
        if args.stream:
            success = test_stream(client, args.gateway_url, args.model, args.api_key, args.timeout)
        else:
            success = test_non_stream(client, args.gateway_url, args.model, args.api_key, args.timeout)

    print()
    print("=" * 60)
    if success:
        print("  ✅ TESTE PASSOU — FactorAI model responded correctly")
    else:
        print("  ❌ TESTE FALHOU — Verifica a configuração do gateway/vLLM")
    print("=" * 60)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
