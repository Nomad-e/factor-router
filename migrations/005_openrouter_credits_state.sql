-- Estado dos créditos OpenRouter (último GET /usage/openrouter/credits).
-- Uma única linha id=1.

-- Se uma execução anterior falhou, pode ficar um type composto
-- `openrouter_credits_state` no catálogo sem a tabela existir.
-- Isso faz `CREATE TABLE` falhar com: `type "openrouter_credits_state" already exists`.
DO $$
BEGIN
  IF EXISTS (
       SELECT 1
         FROM pg_type t
         JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'openrouter_credits_state'
          AND n.nspname = 'public'
     )
     AND NOT EXISTS (
       SELECT 1
         FROM pg_class c
         JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'openrouter_credits_state'
          AND c.relkind = 'r'
          AND n.nspname = 'public'
     ) THEN
    EXECUTE 'DROP TYPE public.openrouter_credits_state';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS openrouter_credits_state (
    id                 smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    remaining_usd      double precision NOT NULL DEFAULT 0,
    total_credits_usd  double precision,
    total_usage_usd    double precision,
    show_alert         boolean NOT NULL DEFAULT false,
    checked_at         timestamptz NOT NULL DEFAULT now(),
    fetch_ok           boolean NOT NULL DEFAULT false
);

INSERT INTO openrouter_credits_state (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

COMMENT ON TABLE openrouter_credits_state IS
    'Snapshot dos créditos OpenRouter; actualizado só em GET /usage/openrouter/credits (admin).';
