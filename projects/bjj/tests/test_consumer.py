"""Consumidor do Kafka do BJJ: validação sem banco e o tratamento de repetidas com o banco real.

Rode com BJJ_TEST_DATABASE_URL=postgresql://bjj:<senha>@localhost:5432/bjj pytest
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

from core import db, stream
from projects.bjj.consumer import handle_item, handle_run, validate_item

DATABASE_URL = os.environ.get("BJJ_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DATABASE_URL, reason="BJJ_TEST_DATABASE_URL não definida")

SOURCE = "teste_consumidor"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _item(**overrides):
    item = {
        "source": SOURCE,
        "source_event_id": "C1",
        "fingerprint": "abc",
        "name": "COPA CONSUMIDOR",
        "start_date": "2026-11-08",
        "end_date": "2026-11-08",
        "city": "CAMPINAS",
        "state": "SP",
        "country": "BR",
        "modality": ["gi"],
        "status": "open",
    }
    return {**item, **overrides}


def _message(item, produced_at, run_id="run-1"):
    return {
        "schema_version": 1,
        "type": "item",
        "project": "bjj",
        "source": SOURCE,
        "run_id": run_id,
        "produced_at": produced_at.isoformat(),
        "item": item,
    }


def _run(run_id, started_at, keys):
    return {
        "schema_version": 1,
        "type": "run_finished",
        "project": "bjj",
        "source": SOURCE,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": started_at.isoformat(),
        "items": len(keys),
        "keys": [f"{SOURCE}:{k}" for k in keys],
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"source_event_id": None},
        {"source": "outra"},
        {"status": "talvez"},
        {"start_date": "08/11/2026"},
        {"modality": "gi"},
    ],
)
def test_item_invalido(overrides):
    with pytest.raises(stream.InvalidMessage):
        validate_item(_message(_item(**overrides), T0))


def test_item_sem_campos_opcionais_ganha_os_padroes():
    item = _item()
    del item["city"], item["modality"]
    assert validate_item(_message(item, T0))["modality"] == []


@pytest.fixture
def apply():
    """Aplica cada mensagem numa transação própria, como o consumidor."""

    def run(handler, message):
        with db.connect(url=DATABASE_URL) as conn:
            return handler(conn, message)

    yield run
    with db.connect(url=DATABASE_URL) as conn:
        conn.execute("DELETE FROM bjj.events WHERE source = %s", (SOURCE,))
        conn.execute("DELETE FROM bjj.crawl_runs WHERE source = %s", (SOURCE,))


def _history(source_event_id):
    with db.connect(url=DATABASE_URL) as conn:
        return conn.execute(
            "SELECT c.run_id, c.change_type, c.field FROM bjj.event_changes c"
            " JOIN bjj.events e ON e.id = c.event_id"
            " WHERE e.source = %s AND e.source_event_id = %s ORDER BY c.id",
            (SOURCE, source_event_id),
        ).fetchall()


@needs_db
def test_repetidas_nao_gravam_de_novo(apply):
    first = _message(_item(), T0)
    assert apply(handle_item, first) == "novo"
    # O Kafka entregou a mesma mensagem outra vez.
    assert apply(handle_item, first) == "repetida"
    # Coleta seguinte, sem mudança no site.
    assert apply(handle_item, _message(_item(), T0 + timedelta(days=1), "run-2")) == "igual"
    assert [h["change_type"] for h in _history("C1")] == ["created"]


@needs_db
def test_mudanca_e_mensagem_antiga(apply):
    apply(handle_item, _message(_item(), T0))
    changed = _message(_item(status="closed", start_date="2026-11-15"), T0 + timedelta(days=1), "run-2")
    assert apply(handle_item, changed) == "alterado (start_date, status)"
    # Relendo o tópico: a versão de T0 é mais velha do que a gravada e não pode desfazer a mudança.
    assert apply(handle_item, _message(_item(), T0)) == "repetida"

    with db.connect(url=DATABASE_URL) as conn:
        status = conn.execute(
            "SELECT status FROM bjj.events WHERE source = %s", (SOURCE,)
        ).fetchone()["status"]
    assert status == "closed"
    history = [(h["run_id"], h["change_type"], h["field"]) for h in _history("C1")]
    assert history == [
        ("run-1", "created", None),
        ("run-2", "updated", "start_date"),
        ("run-2", "updated", "status"),
    ]


@needs_db
def test_fim_de_coleta_marca_removidos_e_ignora_repetida(apply):
    apply(handle_item, _message(_item(), T0))
    apply(handle_item, _message(_item(source_event_id="C2"), T0))
    assert apply(handle_run, _run("run-1", T0, ["C1", "C2"])) == "2 itens, 2 novos, 0 removidos"

    t1 = T0 + timedelta(days=1)
    apply(handle_item, _message(_item(), t1, "run-2"))
    assert apply(handle_run, _run("run-2", t1, ["C1"])) == "1 itens, 0 novos, 1 removidos: COPA CONSUMIDOR"
    assert apply(handle_run, _run("run-2", t1, ["C1"])) == "repetida"
    # Uma coleta mais velha do que a última registrada não mexe em nada.
    assert apply(handle_run, _run("run-0", T0 - timedelta(days=1), ["C1"])).startswith("antiga")

    # C2 voltou ao site na coleta seguinte.
    t2 = T0 + timedelta(days=2)
    assert apply(handle_item, _message(_item(source_event_id="C2"), t2, "run-3")) == "voltou ao site"
    fields = [(h["run_id"], h["field"]) for h in _history("C2") if h["change_type"] == "updated"]
    assert fields == [("run-2", "removed_at"), ("run-3", "removed_at")]

    with db.connect(url=DATABASE_URL) as conn:
        runs = conn.execute(
            "SELECT run_id, items_found, new_items FROM bjj.crawl_runs WHERE source = %s ORDER BY id",
            (SOURCE,),
        ).fetchall()
    assert [(r["run_id"], r["items_found"], r["new_items"]) for r in runs] == [
        ("run-1", 2, 2),
        ("run-2", 1, 0),
    ]


def test_coleta_vazia_e_rejeitada():
    with pytest.raises(stream.InvalidMessage):
        handle_run(None, _run("run-1", T0, []))


def test_chave_de_outra_fonte_e_rejeitada():
    message = _run("run-1", T0, ["C1"])
    message["keys"] = ["outra:C1"]
    with pytest.raises(stream.InvalidMessage):
        handle_run(None, message)
