-- Contagem de requisições por chave em janelas fixas (minuto e dia), para o limite de uso.
CREATE TABLE web.api_key_usage (
    key_id       integer     NOT NULL REFERENCES web.api_keys (id),
    window_kind  text        NOT NULL CHECK (window_kind IN ('minute', 'day')),
    window_start timestamptz NOT NULL,
    hits         integer     NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, window_kind, window_start)
);

CREATE INDEX api_key_usage_window_start_idx ON web.api_key_usage (window_start);
