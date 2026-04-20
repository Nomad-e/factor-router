# TTS via FactorRouter (`/v1/audio/speech`)

O gateway expõe **`POST /v1/audio/speech`** no mesmo estilo OpenAI: corpo JSON com `model`, `input`, e opcionalmente `voice` e `response_format`.

## Fluxo

```
Cliente → FactorRouter :8003 /v1/audio/speech
    → upstream SPEECH_UPSTREAM_URL (factor-speech)
```

## Variáveis de ambiente (gateway)

| Variável | Descrição |
|----------|-----------|
| `SPEECH_UPSTREAM_URL` | URL completa do serviço TTS (ex. `http://127.0.0.1:8091/v1/audio/speech`) |
| `SPEECH_UPSTREAM_TIMEOUT` | Timeout em segundos (default 180) |

## Autenticação e headers

Igual ao resto do proxy: `Authorization: Bearer <api_key>` e todos os headers `X-*` obrigatórios (`X-Turn-Id`, `X-Session-Id`, etc.).

## Exemplo `curl`

```bash
curl -sS -X POST "http://localhost:8003/v1/audio/speech" \
  -H "Authorization: Bearer sk-fai-..." \
  -H "Content-Type: application/json" \
  -H "X-Turn-Id: $(uuidgen)" \
  -H "X-Session-Id: wa-session-1" \
  -H "X-Conversation-Id: conversation-id" \
  -H "X-User-Message: user-message" \
  -H "X-User-Id: user-id" \
  -H "X-User-Name: user-name" \
  -H "X-User-Email: user-email" \
  -H "X-Company-Id: company-id" \
  -H "X-Company-Name: comapny-name" \
  -d '{"model":"chatterbox","input":"Olá.","response_format":"opus" "voice":"EU_00"}' \
  --output /tmp/out.ogg
```
