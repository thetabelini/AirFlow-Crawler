-- Histórico de mudanças por evento, preenchido por um trigger em bjj.events.
-- Cada linha é um evento criado, ou um campo que mudou (com o valor antigo e o novo).
-- A execução da DAG que fez a mudança vem de set_config('crawler.run_id', ...).

-- Preenchido quando o evento some do site (não aparece numa coleta); limpo se ele voltar.
ALTER TABLE bjj.events ADD COLUMN removed_at timestamptz;

CREATE TABLE bjj.event_changes (
    id          bigserial   PRIMARY KEY,
    event_id    bigint      NOT NULL REFERENCES bjj.events (id) ON DELETE CASCADE,
    changed_at  timestamptz NOT NULL DEFAULT now(),
    run_id      text,
    change_type text        NOT NULL CHECK (change_type IN ('created', 'updated')),
    field       text,
    old_value   text,
    new_value   text
);

CREATE INDEX event_changes_event_idx ON bjj.event_changes (event_id, changed_at);
CREATE INDEX event_changes_changed_at_idx ON bjj.event_changes (changed_at);

CREATE FUNCTION bjj.log_event_changes() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    tracked  text[] := ARRAY[
        'name', 'edition', 'start_date', 'end_date', 'city', 'state', 'country',
        'venue', 'organizer', 'modality', 'event_url', 'registration_url',
        'registration_deadline', 'status', 'fingerprint', 'removed_at'
    ];
    run      text := NULLIF(current_setting('crawler.run_id', true), '');
    old_row  jsonb;
    new_row  jsonb := to_jsonb(NEW);
    col      text;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO bjj.event_changes (event_id, run_id, change_type)
        VALUES (NEW.id, run, 'created');
        RETURN NEW;
    END IF;

    old_row := to_jsonb(OLD);
    FOREACH col IN ARRAY tracked LOOP
        IF old_row -> col IS DISTINCT FROM new_row -> col THEN
            INSERT INTO bjj.event_changes (event_id, run_id, change_type, field, old_value, new_value)
            VALUES (NEW.id, run, 'updated', col, old_row ->> col, new_row ->> col);
        END IF;
    END LOOP;
    RETURN NEW;
END
$$;

CREATE TRIGGER events_log_changes
AFTER INSERT OR UPDATE ON bjj.events
FOR EACH ROW EXECUTE FUNCTION bjj.log_event_changes();

-- Eventos que já existiam: o registro de criação com a data em que apareceram pela primeira vez.
INSERT INTO bjj.event_changes (event_id, changed_at, change_type)
SELECT id, first_seen_at, 'created' FROM bjj.events;
