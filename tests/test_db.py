"""Precisa de um Postgres com o schema de sql/ aplicado.

Rode com BJJ_TEST_DATABASE_URL=postgresql://bjj:<senha>@localhost:5432/bjj pytest
"""

import os
from datetime import datetime, timezone

import pytest

from crawler import db

DATABASE_URL = os.environ.get("BJJ_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="BJJ_TEST_DATABASE_URL não definida")


@pytest.fixture
def conn():
    with db.connect(DATABASE_URL) as conn:
        yield conn
        conn.rollback()


def _event(**overrides):
    event = {
        "source": "teste",
        "source_event_id": "P1",
        "fingerprint": "abc",
        "name": "COPA TESTE",
        "start_date": "2026-11-08",
        "end_date": "2026-11-08",
        "city": "CAMPINAS",
        "state": "SP",
        "country": "BR",
        "modality": ["gi"],
        "status": "open",
    }
    return {**event, **overrides}


def test_upsert_devolve_so_os_novos(conn):
    assert len(db.upsert_events(conn, [_event(), _event(source_event_id="P2")])) == 2
    assert db.upsert_events(conn, [_event(status="closed"), _event(source_event_id="P3")]) == [
        _event(source_event_id="P3")
    ]
    status = conn.execute(
        "SELECT status FROM bjj.events WHERE source = 'teste' AND source_event_id = 'P1'"
    ).fetchone()["status"]
    assert status == "closed"


def test_record_run(conn):
    db.record_run(
        conn, "run-1", "teste", datetime.now(timezone.utc), events_found=3, new_events=1
    )
    row = conn.execute("SELECT * FROM bjj.crawl_runs WHERE run_id = 'run-1'").fetchone()
    assert (row["events_found"], row["new_events"], row["pages_fetched"]) == (3, 1, 1)
