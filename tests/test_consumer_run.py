"""O laço do consumidor com Kafka e banco falsos: roteamento, DLQ e ordem dos commits."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
import pytest

from consumer.run import Runner
from core import stream


class FakeMsg:
    def __init__(self, topic, value, key=b"k", partition=0, offset=7):
        self._topic, self._value, self._key = topic, value, key
        self._partition, self._offset = partition, offset

    def topic(self):
        return self._topic

    def value(self):
        return self._value

    def key(self):
        return self._key

    def partition(self):
        return self._partition

    def offset(self):
        return self._offset


class FakeConn:
    def __init__(self, log):
        self.log = log

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            self.log.append("rollback")
            raise
        self.log.append("db commit")


class FakeProducer:
    def __init__(self, log):
        self.log, self.sent = log, []

    def produce(self, topic, key, value, on_delivery):
        self.sent.append((topic, key, json.loads(value)))
        self.log.append(f"dlq {topic}")

    def flush(self, timeout):
        return 0


class FakeConsumer:
    def __init__(self, log):
        self.log = log

    def commit(self, message, asynchronous):
        self.log.append(f"offset commit {message.offset()}")


def _message(**overrides):
    return json.dumps(
        {"schema_version": 1, "type": "item", "project": "bjj", "source": "s", **overrides}
    ).encode()


@pytest.fixture
def setup():
    log = []

    def handle_item(conn, message):
        if message.get("boom") == "dados":
            raise psycopg.DataError("valor inválido")
        if message.get("boom") == "banco":
            raise psycopg.OperationalError("banco fora do ar")
        log.append("handle_item")
        return "novo"

    def handle_run(conn, message):
        log.append("handle_run")
        return "ok"

    handler = SimpleNamespace(handle_item=handle_item, handle_run=handle_run)
    producer = FakeProducer(log)
    runner = Runner({"bjj": handler}, FakeConsumer(log), producer, {"bjj": FakeConn(log)})
    return runner, log, producer


def test_rotas_por_topico(setup):
    runner, log, _ = setup
    assert runner.routes == {"bjj.events.raw": ("bjj", "item"), "bjj.runs": ("bjj", "run_finished")}
    runner.handle(FakeMsg("bjj.runs", _message(type="run_finished")))
    assert log == ["handle_run", "db commit", "offset commit 7"]


def test_offset_so_depois_do_banco(setup):
    runner, log, _ = setup
    runner.handle(FakeMsg("bjj.events.raw", _message()))
    assert log == ["handle_item", "db commit", "offset commit 7"]


@pytest.mark.parametrize(
    "value",
    [b"nao-e-json", _message(schema_version=2), _message(type="run_finished"), _message(boom="dados")],
)
def test_mensagem_invalida_vai_para_dlq_e_segue(setup, value):
    runner, log, producer = setup
    runner.handle(FakeMsg("bjj.events.raw", value, offset=3))
    assert log[-2:] == ["dlq bjj.events.dlq", "offset commit 3"]
    topic, key, rejected = producer.sent[0]
    assert (topic, key, rejected["offset"]) == ("bjj.events.dlq", b"k", 3)
    assert rejected["original"] == value.decode()


def test_banco_fora_do_ar_derruba_sem_commit(setup):
    runner, log, producer = setup
    with pytest.raises(psycopg.OperationalError):
        runner.handle(FakeMsg("bjj.events.raw", _message(boom="banco")))
    assert log == ["rollback"] and not producer.sent
