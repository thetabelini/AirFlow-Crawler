"""Gravação dos eventos em bjj.events."""

import psycopg

UPSERT_EVENT = """
INSERT INTO bjj.events (
    source, source_event_id, fingerprint, name, edition, start_date, end_date,
    city, state, country, venue, organizer, modality,
    event_url, registration_url, registration_deadline, status
) VALUES (
    %(source)s, %(source_event_id)s, %(fingerprint)s, %(name)s, %(edition)s,
    %(start_date)s, %(end_date)s, %(city)s, %(state)s, %(country)s, %(venue)s,
    %(organizer)s, %(modality)s, %(event_url)s, %(registration_url)s,
    %(registration_deadline)s, %(status)s
)
ON CONFLICT (source, source_event_id) DO UPDATE SET
    fingerprint           = EXCLUDED.fingerprint,
    name                  = EXCLUDED.name,
    edition               = EXCLUDED.edition,
    start_date            = EXCLUDED.start_date,
    end_date              = EXCLUDED.end_date,
    city                  = EXCLUDED.city,
    state                 = EXCLUDED.state,
    country               = EXCLUDED.country,
    venue                 = EXCLUDED.venue,
    organizer             = EXCLUDED.organizer,
    modality              = EXCLUDED.modality,
    event_url             = EXCLUDED.event_url,
    registration_url      = EXCLUDED.registration_url,
    registration_deadline = EXCLUDED.registration_deadline,
    status                = EXCLUDED.status,
    last_seen_at          = now()
RETURNING (xmax = 0) AS inserted
"""

EVENT_DEFAULTS = {
    "edition": None,
    "start_date": None,
    "end_date": None,
    "city": None,
    "state": None,
    "country": None,
    "venue": None,
    "organizer": None,
    "modality": [],
    "event_url": None,
    "registration_url": None,
    "registration_deadline": None,
    "status": "open",
}


def upsert_events(conn: psycopg.Connection, events: list[dict]) -> list[dict]:
    """Grava os eventos e devolve só os que ainda não existiam."""
    new_events = []
    with conn.cursor() as cur:
        for event in events:
            cur.execute(UPSERT_EVENT, {**EVENT_DEFAULTS, **event})
            if cur.fetchone()["inserted"]:
                new_events.append(event)
    return new_events
