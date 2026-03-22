-- migrations/004_unique_turn_id.sql
--
-- Adiciona constraint UNIQUE ao turn_id para evitar registos duplicados.
-- O turn_id identifica um único turno agentico — deve ser único no DB.
-- Usa ON CONFLICT DO NOTHING no INSERT para ser idempotente.
--
-- ATENÇÃO: remove duplicados existentes antes de criar o índice UNIQUE.
-- Mantém apenas o registo com mais tokens (source=usage_real em preferência).

-- 1. Remove duplicados — mantém o registo com maior total_tokens por turn_id
DELETE FROM llm_usage_log
WHERE id NOT IN (
    SELECT DISTINCT ON (turn_id) id
    FROM llm_usage_log
    ORDER BY turn_id, total_tokens DESC, id ASC
);

-- 2. Cria índice UNIQUE no turn_id
CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_usage_log_turn_id_unique
    ON llm_usage_log (turn_id);

-- Drop o índice não-unique anterior se existir
DROP INDEX IF EXISTS idx_llm_usage_log_turn_id;