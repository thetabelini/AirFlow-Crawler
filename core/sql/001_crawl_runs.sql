-- Aplicado no banco de cada projeto, com :schema = nome do projeto.
CREATE SCHEMA IF NOT EXISTS :"schema";

CREATE TABLE :"schema".crawl_runs (
    id            bigserial PRIMARY KEY,
    run_id        text        NOT NULL,
    source        text        NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    pages_fetched integer     NOT NULL DEFAULT 0,
    items_found   integer     NOT NULL DEFAULT 0,
    new_items     integer     NOT NULL DEFAULT 0,
    errors        text
);

CREATE INDEX crawl_runs_source_started_idx ON :"schema".crawl_runs (source, started_at DESC);
