import json
from datetime import date, datetime, timezone

import pytest

from core import stream


class FakeMessage:
    def __init__(self, topic):
        self._topic = topic

    def topic(self):
        return self._topic


class FakeProducer:
    """Guarda o que foi produzido e confirma (ou recusa) a entrega no flush, como o real."""

    def __init__(self, fail_topic=None, pending=0):
        self.sent = []
        self.fail_topic = fail_topic
        self.pending = pending
        self._callbacks = []

    def produce(self, topic, key, value, on_delivery):
        self.sent.append((topic, key.decode(), json.loads(value)))
        self._callbacks.append((topic, on_delivery))

    def poll(self, timeout):
        return 0

    def flush(self, timeout):
        for topic, callback in self._callbacks:
            callback("falhou" if topic == self.fail_topic else None, FakeMessage(topic))
        self._callbacks = []
        return self.pending


STARTED = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
ITEMS = [
    {"source_event_id": "1", "name": "COPA A", "start_date": date(2026, 11, 8)},
    {"source_event_id": "2", "name": "COPA B", "start_date": "2026-12-01"},
]


def test_enabled(monkeypatch):
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    assert not stream.enabled()
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", " ")
    assert not stream.enabled()
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    assert stream.enabled()


def test_publica_itens_e_depois_o_fim_da_coleta():
    producer = FakeProducer()
    assert stream.publish_run("bjj", "soucompetidor", "run-1", STARTED, ITEMS, producer=producer) == 2

    topics = [topic for topic, _, _ in producer.sent]
    assert topics == ["bjj.events.raw", "bjj.events.raw", "bjj.runs"]

    _, key, message = producer.sent[0]
    assert key == "soucompetidor:1"
    assert message["type"] == "item" and message["run_id"] == "run-1"
    assert message["schema_version"] == stream.SCHEMA_VERSION
    assert message["item"]["start_date"] == "2026-11-08"

    _, key, run = producer.sent[-1]
    assert key == "soucompetidor"
    assert run["type"] == "run_finished" and run["items"] == 2
    assert run["keys"] == ["soucompetidor:1", "soucompetidor:2"]
    assert run["started_at"] == STARTED.isoformat()


def test_coleta_vazia_ainda_avisa_o_fim():
    producer = FakeProducer()
    assert stream.publish_run("bjj", "x", "run-1", STARTED, [], producer=producer) == 0
    assert [(t, m["keys"]) for t, _, m in producer.sent] == [("bjj.runs", [])]


@pytest.mark.parametrize("producer", [FakeProducer(fail_topic="bjj.runs"), FakeProducer(pending=1)])
def test_falha_se_algo_nao_foi_entregue(producer):
    with pytest.raises(RuntimeError, match="Kafka"):
        stream.publish_run("bjj", "x", "run-1", STARTED, ITEMS, producer=producer)


def test_encode_recusa_tipo_desconhecido():
    with pytest.raises(TypeError):
        stream.encode({"x": object()})


def test_decode_aceita_so_objeto_json():
    assert stream.decode(b'{"a": 1}') == {"a": 1}
    for value in (b"nao-e-json", b"[1, 2]", b"\xff\xfe", None):
        with pytest.raises(stream.InvalidMessage):
            stream.decode(value)


def test_check_confere_versao_tipo_e_projeto():
    ok = {"schema_version": stream.SCHEMA_VERSION, "type": "item", "project": "bjj"}
    stream.check(ok, "bjj", "item")
    for wrong in ({"schema_version": 99}, {"type": "run_finished"}, {"project": "outro"}):
        with pytest.raises(stream.InvalidMessage):
            stream.check({**ok, **wrong}, "bjj", "item")


def test_parse_time_exige_fuso():
    assert stream.parse_time({"t": STARTED.isoformat()}, "t") == STARTED
    for value in (None, "ontem", "2026-10-01T12:00:00"):
        with pytest.raises(stream.InvalidMessage):
            stream.parse_time({"t": value}, "t")


def test_dlq_guarda_a_mensagem_original_e_o_motivo():
    message = stream.dlq_message("bjj.events.raw", 2, 41, b'{"quebrado"', "não é JSON")
    assert message["type"] == "rejected" and message["original"] == '{"quebrado"'
    assert (message["topic"], message["partition"], message["offset"]) == ("bjj.events.raw", 2, 41)
    assert json.loads(stream.encode(message))["error"] == "não é JSON"
