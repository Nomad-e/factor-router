-- migrations/003_add_turn_id_to_llm_usage_log.sql
--
-- Adiciona o turn_id à tabela llm_usage_log.
-- Permite correlacionar registos de custo com o turno exacto do agente.
--
-- Executar:
--   docker exec -i factor_router_postgres psql -U factor_router -d factor_router -f - < migrations/003_add_turn_id_to_llm_usage_log.sql

ALTER TABLE llm_usage_log
    ADD COLUMN IF NOT EXISTS turn_id TEXT;

CREATE INDEX IF NOT EXISTS idx_llm_usage_log_turn_id
    ON llm_usage_log (turn_id);

COMMENT ON COLUMN llm_usage_log.turn_id IS
    'UUID v4 gerado pelo agente no início de cada turno (X-Turn-Id). '
    'Permite correlacionar múltiplos calls ao LLM dentro do mesmo turno.';