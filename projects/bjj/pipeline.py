"""O que o gerador de DAGs chama depois do parser: normalize() e store()."""

import logging

import psycopg

from projects.bjj.normalize import normalize_event as normalize
from projects.bjj.store import mark_removed, upsert_events

__all__ = ["normalize", "store"]

log = logging.getLogger(__name__)


def store(conn: psycopg.Connection, events: list[dict]) -> list[dict]:
    """Grava a coleta, marca o que sumiu do site e devolve os eventos novos."""
    new_events = upsert_events(conn, events)
    for source in sorted({e["source"] for e in events}):
        for removed in mark_removed(conn, source):
            log.info("sumiu do site: %s | %s", removed["source_event_id"], removed["name"])
    return new_events
