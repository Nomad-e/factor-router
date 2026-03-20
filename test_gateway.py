"""
test_gateway.py

Script de teste completo do FactorRouter Gateway.
Simula uma app real a fazer requests ao gateway.

Testa:
    1. Health check
    2. Autenticação com key inválida → 401
    3. Headers em falta → 400
    4. Chat completions sem streaming
    5. Chat completions com streaming SSE
    6. Verificação do registo de custos em /usage/logs

Uso:
    python test_gateway.py

Configurar as variáveis no topo do ficheiro antes de correr.
"""
import asyncio
import json
import uuid
import httpx

# ─────────────────────────────────────────────────────────────────────────────
# Configuração — preenche antes de correr
# ─────────────────────────────────────────────────────────────────────────────

GATEWAY_URL   = "http://localhost:8003"
API_KEY       = "sk-fai-90f75e1a2e503d4edfea7d77bdec8a3c14ff6e640fd55913"
ADMIN_SECRET  = "sk-fai-4c004a3b72355d6974bac2fb46ca8244199ebe27743861a46219c022ef58f928682ceaaea001407b98f6e520028e8b20d675845a99d7f149d9b13bc2d9c2ca5aa0ee5d9130a703795b30683f66887031b030cc8e632b2e20dddf5b2c3006ab33c7a63ece6de3e160466ec764bb180ccd029247ef42f4990a2ae0f3daf9f724cf5f3564462b98432406ba34af323e866bdfa75d5c219d1b57abfb775f3cf1fa1ddff4e9e4ea30cbe32a7d61f9bc6e697c0dbba14850c56f22091bf96af5461e86ada8f1b2333f5af8b895a999ae7744af1afb885f12e1e24d92b9b7e94abf3bb050e34a69b68780b53b4dc9820e275763273876e012fa58fcbfc479b56963049cfdc49e14"   # só necessário para verificar /usage/logs no fim

# Contexto simulado da app (como se fossem os default_headers do OpenAI client)
APP_ID        = "bluma"
SESSION_ID    = f"test-session-{uuid.uuid4().hex[:8]}"
COMPANY_ID    = "test-company-001"
COMPANY_NAME  = "Empresa Teste Lda"
USER_ID       = "user-42"
USER_NAME     = "Alex Fonseca"
USER_EMAIL    = "alex@factorai.pt"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ascii(value: str) -> str:
    """Encode para ASCII substituindo caracteres especiais — headers HTTP sao ASCII puro."""
    return value.encode("ascii", errors="replace").decode("ascii")


def make_headers(turn_id: str, user_message: str) -> dict:
    """Constrói os headers obrigatórios tal como uma app real faria."""
    return {
        "Authorization":     f"Bearer {API_KEY}",
        "Content-Type":      "application/json",
        "X-App-Id":          APP_ID,
        "X-Turn-Id":         turn_id,
        "X-Session-Id":      SESSION_ID,
        "X-Conversation-Id": "null",
        "X-User-Message":    _ascii(user_message[:300]),
        "X-User-Id":         USER_ID,
        "X-User-Name":       _ascii(USER_NAME),
        "X-User-Email":      USER_EMAIL,
        "X-Company-Id":      COMPANY_ID,
        "X-Company-Name":    _ascii(COMPANY_NAME),
    }


def sep(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


def ok(msg: str):   print(f"  ✓  {msg}")
def err(msg: str):  print(f"  ✗  {msg}")
def info(msg: str): print(f"     {msg}")


# ─────────────────────────────────────────────────────────────────────────────
# Testes
# ─────────────────────────────────────────────────────────────────────────────

async def test_health(client: httpx.AsyncClient):
    sep("1. Health check")
    r = await client.get(f"{GATEWAY_URL}/health")
    if r.status_code == 200:
        data = r.json()
        ok(f"Status: {data['status']}  |  Version: {data['version']}")
        info(f"Upstream: {data['upstream']}")
    else:
        err(f"Falhou: {r.status_code} {r.text}")


async def test_invalid_key(client: httpx.AsyncClient):
    sep("2. Autenticação com key inválida → deve dar 401")
    turn_id = str(uuid.uuid4())
    r = await client.post(
        f"{GATEWAY_URL}/v1/chat/completions",
        headers={
            "Authorization":     "Bearer sk-fai-chave-invalida-aqui",
            "Content-Type":      "application/json",
            "X-App-Id":          APP_ID,
            "X-Turn-Id":         turn_id,
            "X-Session-Id":      SESSION_ID,
            "X-Conversation-Id": "null",
            "X-User-Message":    "teste",
            "X-User-Id":         USER_ID,
            "X-User-Name":       USER_NAME,
            "X-User-Email":      USER_EMAIL,
            "X-Company-Id":      COMPANY_ID,
            "X-Company-Name":    COMPANY_NAME,
        },
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "teste"}]},
    )
    if r.status_code == 401:
        ok(f"401 recebido corretamente: {r.json()['detail']['error']}")
    else:
        err(f"Esperava 401, recebeu {r.status_code}")


async def test_missing_header(client: httpx.AsyncClient):
    sep("3. Header obrigatório em falta → deve dar 400")
    r = await client.post(
        f"{GATEWAY_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type":  "application/json",
            # X-Turn-Id em falta propositadamente
            "X-App-Id":      APP_ID,
            "X-Session-Id":  SESSION_ID,
        },
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "teste"}]},
    )
    if r.status_code == 400:
        detail = r.json().get("detail", {})
        ok(f"400 recebido corretamente")
        info(f"Header em falta: {detail.get('header', '?')}")
        info(f"Mensagem: {detail.get('message', '?')[:80]}")
    else:
        err(f"Esperava 400, recebeu {r.status_code}: {r.text[:200]}")


async def test_chat_no_stream(client: httpx.AsyncClient):
    sep("4. Chat completions — sem streaming")
    turn_id     = str(uuid.uuid4())
    user_msg    = "Responde apenas com: 'Gateway a funcionar!'"
    headers     = make_headers(turn_id, user_msg)

    info(f"Turn-Id:    {turn_id[:18]}...")
    info(f"Session-Id: {SESSION_ID}")

    r = await client.post(
        f"{GATEWAY_URL}/v1/chat/completions",
        headers=headers,
        json={
            "model":    "gpt-4o-mini",
            "messages": [{"role": "user", "content": user_msg}],
            "stream":   False,
        },
        timeout=60,
    )

    if r.status_code == 200:
        data     = r.json()
        content  = data["choices"][0]["message"]["content"]
        model    = data.get("model", "?")
        usage    = data.get("usage", {})
        ok(f"Resposta recebida")
        info(f"Modelo usado:  {model}")
        info(f"Tokens:        {usage.get('prompt_tokens', '?')} prompt + {usage.get('completion_tokens', '?')} completion")
        info(f"Resposta:      {content[:100]}")
    else:
        err(f"Falhou: {r.status_code}")
        info(r.text[:300])


async def test_chat_stream(client: httpx.AsyncClient):
    sep("5. Chat completions — com streaming SSE")
    turn_id  = str(uuid.uuid4())
    user_msg = "Count to 5, one number per line."
    headers  = make_headers(turn_id, user_msg)

    info(f"Turn-Id: {turn_id[:18]}...")

    chunks_received = 0
    full_response   = ""

    async with client.stream(
        "POST",
        f"{GATEWAY_URL}/v1/chat/completions",
        headers=headers,
        json={
            "model":    "gpt-4o-mini",
            "messages": [{"role": "user", "content": user_msg}],
            "stream":   True,
        },
        timeout=60,
    ) as r:
        if r.status_code != 200:
            err(f"Falhou: {r.status_code}")
            return

        async for line in r.aiter_lines():
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk   = json.loads(data_str)
                delta   = chunk["choices"][0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_response += content
                    chunks_received += 1
                    print(f"  chunk #{chunks_received:02d}: {repr(content)}")
            except json.JSONDecodeError:
                pass

    ok(f"Stream concluído — {chunks_received} chunks recebidos")
    info(f"Resposta completa: {full_response.strip()[:100]}")


async def test_usage_logs(client: httpx.AsyncClient):
    sep("6. Centro de custos — verificar registo de uso")
    if not ADMIN_SECRET:
        info("ADMIN_SECRET não configurado — a saltar este teste")
        info("Define ADMIN_SECRET no topo do ficheiro para testar")
        return

    # Aguarda um momento para o flush assíncrono terminar
    info("A aguardar flush assíncrono (2s)...")
    await asyncio.sleep(2)

    r = await client.get(
        f"{GATEWAY_URL}/usage/logs",
        headers={
            "Authorization": f"Bearer {API_KEY}",
        },
        params={
            "app_id":  APP_ID,
            "limit":   5,
        },
    )

    if r.status_code == 200:
        data  = r.json()
        items = data.get("items", [])
        ok(f"Logs recebidos: {len(items)} registos")
        for item in items[:3]:
            import json as _json
            meta = item.get("meta") or {}
            if isinstance(meta, str):
                meta = _json.loads(meta)
            info(
                f"  model={item.get('model_id','?')} | "
                f"tokens={item.get('total_tokens','?')} | "
                f"cost=${item.get('total_cost_usd','?')} | "
                f"source={meta.get('source','?')}"
            )
    elif r.status_code == 501:
        info("usage/logs ainda não implementado (stub) — normal nesta fase")
    else:
        err(f"Falhou: {r.status_code} {r.text[:200]}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  FactorRouter Gateway — Teste de integração")
    print(f"  URL:     {GATEWAY_URL}")
    print(f"  App:     {APP_ID}")
    print(f"  Session: {SESSION_ID}")
    print("=" * 60)

    async with httpx.AsyncClient() as client:
        await test_health(client)
        await test_invalid_key(client)
        await test_missing_header(client)
        await test_chat_no_stream(client)
        await test_chat_stream(client)
        await test_usage_logs(client)

    print(f"\n{'=' * 60}")
    print("  Testes concluídos.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())