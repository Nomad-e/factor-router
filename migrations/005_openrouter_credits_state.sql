-- Estado dos créditos OpenRouter (último GET /usage/openrouter/credits).
-- Uma única linha id=1.

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
