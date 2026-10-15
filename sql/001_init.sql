CREATE SCHEMA IF NOT EXISTS bjj;

CREATE TABLE bjj.events (
    id                    bigserial PRIMARY KEY,
    source                text        NOT NULL,
    source_event_id       text        NOT NULL,
    fingerprint           text        NOT NULL,
    name                  text        NOT NULL,
    start_date            date,
    end_date              date,
    city                  text,
    state                 text,
    country               text,
    venue                 text,
    organizer             text,
    modality              text[]      NOT NULL DEFAULT '{}',
    registration_url      text,
    registration_deadline date,
    status                text        NOT NULL DEFAULT 'open'
                                      CHECK (status IN ('open', 'closed', 'cancelled')),
    first_seen_at         timestamptz NOT NULL DEFAULT now(),
    last_seen_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_event_id)
);

-- Não é único: o mesmo campeonato pode vir de mais de uma fonte.
CREATE INDEX events_fingerprint_idx ON bjj.events (fingerprint);
CREATE INDEX events_start_date_idx ON bjj.events (start_date);

CREATE TABLE bjj.crawl_runs (
    id            bigserial PRIMARY KEY,
    run_id        text        NOT NULL,
    source        text        NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    pages_fetched integer     NOT NULL DEFAULT 0,
    events_found  integer     NOT NULL DEFAULT 0,
    new_events    integer     NOT NULL DEFAULT 0,
    errors        text
);

CREATE INDEX crawl_runs_source_started_idx ON bjj.crawl_runs (source, started_at DESC);
