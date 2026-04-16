-- migrations/002_llm_usage_log.sql
--
-- Tabela de registo de uso de LLM por turno.
-- Executar:
--   psql $DATABASE_URL -f migrations/002_llm_usage_log.sql

-- Se uma execução anterior falhou, pode ficar um type composto `llm_usage_log`
-- no catálogo sem a tabela existir. Isso faz `CREATE TABLE` falhar com:
-- `type "llm_usage_log" already exists`.
-- Para tornar a migração reexecutável, removemos o type apenas quando a tabela não existir.
DO $$
BEGIN
  IF EXISTS (
       SELECT 1
         FROM pg_type t
         JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'llm_usage_log'
          AND n.nspname = 'public'
     )
     AND NOT EXISTS (
       SELECT 1
         FROM pg_class c
         JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'llm_usage_log'
          AND c.relkind = 'r'
          AND n.nspname = 'public'
     ) THEN
    EXECUTE 'DROP TYPE public.llm_usage_log';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS llm_usage_log (
    id                  BIGSERIAL       PRIMARY KEY,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Identidade / contexto (vem dos headers X-* do agente)
    app_id              TEXT,
    chat_session_id     TEXT            NOT NULL,
    user_id             TEXT,
    user_name           TEXT,
    user_email          TEXT,
    company_id          TEXT,
    company_name        TEXT,
    conversation_id     TEXT,
    user_message        TEXT,

    -- Modelo e tokens
    model_id            TEXT            NOT NULL,
    prompt_tokens       INTEGER         NOT NULL,
    completion_tokens   INTEGER         NOT NULL,
    total_tokens        INTEGER         NOT NULL,

    -- Preços (snapshot do momento do registo)
    input_price_per_1m  NUMERIC(10,4)   NOT NULL DEFAULT 0,
    output_price_per_1m NUMERIC(10,4)   NOT NULL DEFAULT 0,

    -- Custos calculados
    input_cost_usd      NUMERIC(12,6)   NOT NULL DEFAULT 0,
    output_cost_usd     NUMERIC(12,6)   NOT NULL DEFAULT 0,
    total_cost_usd      NUMERIC(12,6)   NOT NULL DEFAULT 0,

    -- Extra
    tool_calls_count    INTEGER         NOT NULL DEFAULT 0,
    meta                JSONB
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_log_app_id
    ON llm_usage_log (app_id);

CREATE INDEX IF NOT EXISTS idx_llm_usage_log_company_id
    ON llm_usage_log (company_id);

CREATE INDEX IF NOT EXISTS idx_llm_usage_log_session_id
    ON llm_usage_log (chat_session_id);

CREATE INDEX IF NOT EXISTS idx_llm_usage_log_created_at
    ON llm_usage_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_log_model_id
    ON llm_usage_log (model_id);