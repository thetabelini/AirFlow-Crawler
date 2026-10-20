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


def test_historico_de_mudancas():
    """Três coletas em transações separadas, como na DAG."""
    from projects.bjj.pipeline import store

    source = "teste_historico"
    a = _event(source=source, source_event_id="H1", name="COPA A", status="open")
    b = _event(source=source, source_event_id="H2", name="COPA B")

    def coleta(run_id, eventos):
        with db.connect(url=DATABASE_URL) as conn:
            db.set_run_id(conn, run_id)
            return store(conn, eventos)

    try:
        assert len(coleta("run-1", [a, b])) == 2
        coleta("run-2", [{**a, "status": "closed", "start_date": "2026-11-15"}])  # B sumiu
        coleta("run-3", [{**a, "status": "closed", "start_date": "2026-11-15"}, b])  # B voltou

        with db.connect(url=DATABASE_URL) as conn:
            rows = conn.execute(
                "SELECT e.source_event_id AS sid, c.run_id, c.change_type, c.field,"
                " c.old_value, c.new_value FROM bjj.event_changes c"
                " JOIN bjj.events e ON e.id = c.event_id WHERE e.source = %s"
                " ORDER BY c.id",
                (source,),
            ).fetchall()
            removed = conn.execute(
                "SELECT removed_at FROM bjj.events WHERE source = %s AND source_event_id = 'H2'",
                (source,),
            ).fetchone()["removed_at"]

        resumo = [(r["sid"], r["run_id"], r["change_type"], r["field"]) for r in rows]
        assert ("H1", "run-1", "created", None) in resumo
        assert ("H2", "run-1", "created", None) in resumo
        assert ("H1", "run-2", "updated", "status") in resumo
        assert ("H1", "run-2", "updated", "start_date") in resumo
        assert ("H2", "run-2", "updated", "removed_at") in resumo
        assert ("H2", "run-3", "updated", "removed_at") in resumo
        status = next(r for r in rows if r["field"] == "status")
        assert (status["old_value"], status["new_value"]) == ("open", "closed")
        sumiu, voltou = [r for r in rows if r["field"] == "removed_at"]
        assert sumiu["old_value"] is None and sumiu["new_value"] is not None
        assert voltou["new_value"] is None and removed is None
        # A 3ª coleta não mudou nada em H1, então não gera linha para ele.
        assert not [r for r in rows if r["sid"] == "H1" and r["run_id"] == "run-3"]
    finally:
        with db.connect(url=DATABASE_URL) as conn:
            conn.execute("DELETE FROM bjj.events WHERE source = %s", (source,))
