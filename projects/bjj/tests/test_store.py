"""Precisa do banco bjj com as migrações aplicadas (serviço db-init).

Rode com BJJ_TEST_DATABASE_URL=postgresql://bjj:<senha>@localhost:5432/bjj pytest
"""

import os
from datetime import datetime, timezone

import pytest

from core import db
from projects.bjj.store import upsert_events

DATABASE_URL = os.environ.get("BJJ_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="BJJ_TEST_DATABASE_URL não definida")


@pytest.fixture
def conn():
    with db.connect(url=DATABASE_URL) as conn:
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
    assert len(upsert_events(conn, [_event(), _event(source_event_id="P2")])) == 2
    assert upsert_events(conn, [_event(status="closed"), _event(source_event_id="P3")]) == [
        _event(source_event_id="P3")
    ]
    status = conn.execute(
        "SELECT status FROM bjj.events WHERE source = 'teste' AND source_event_id = 'P1'"
    ).fetchone()["status"]
    assert status == "closed"


def test_record_run_no_schema_do_projeto(conn):
    db.record_run(
        conn, "bjj", "run-1", "teste", datetime.now(timezone.utc), items_found=3, new_items=1
    )
    row = conn.execute("SELECT * FROM bjj.crawl_runs WHERE run_id = 'run-1'").fetchone()
    assert (row["items_found"], row["new_items"], row["pages_fetched"]) == (3, 1, 1)
