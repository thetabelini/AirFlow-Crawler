CREATE SCHEMA IF NOT EXISTS web;

-- Chaves de API do serviço web. Só o hash (SHA-256) é guardado; a chave aparece uma vez, na criação.
CREATE TABLE web.api_keys (
    id           serial      PRIMARY KEY,
    name         text        NOT NULL,
    key_hash     text        NOT NULL UNIQUE,
    key_prefix   text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz,
    last_used_at timestamptz,
    requests     bigint      NOT NULL DEFAULT 0
);

-- Uma chave ativa por nome; revogadas ficam no histórico.
CREATE UNIQUE INDEX api_keys_active_name_idx ON web.api_keys (name) WHERE revoked_at IS NULL;
