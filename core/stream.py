"""Publicação dos itens coletados no Kafka (ligada quando KAFKA_BOOTSTRAP_SERVERS está definida).

Tópicos de cada projeto (criados por scripts/kafka-init.sh):
  <projeto>.events.raw   um item normalizado por mensagem, chave "<fonte>:<source_event_id>"
  <projeto>.runs         uma mensagem por coleta, com todas as chaves vistas
  <projeto>.events.dlq   reservado ao consumidor, para itens rejeitados

Formato das mensagens: docs/kafka.md.
"""

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal

SCHEMA_VERSION = 1


def enabled() -> bool:
    return bool(os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip())


def topics(project: str) -> dict[str, str]:
    return {
        "raw": f"{project}.events.raw",
        "runs": f"{project}.runs",
        "dlq": f"{project}.events.dlq",
    }


def item_key(source: str, item: dict) -> str:
    return f"{source}:{item['source_event_id']}"


def _default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"não sei converter {type(value).__name__} para JSON")


def encode(message: dict) -> bytes:
    return json.dumps(message, default=_default, ensure_ascii=False).encode()


def item_message(project: str, source: str, run_id: str, item: dict, produced_at: datetime) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "item",
        "project": project,
        "source": source,
        "run_id": run_id,
        "produced_at": produced_at,
        "item": item,
    }


def run_message(
    project: str,
    source: str,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    keys: list[str],
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "run_finished",
        "project": project,
        "source": source,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "items": len(keys),
        "keys": keys,
    }


def make_producer(client_id: str):
    from confluent_kafka import Producer

    return Producer(
        {
            "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            "client.id": client_id,
            # Só considera entregue depois de gravado; com idempotência, uma nova tentativa
            # do próprio produtor não duplica a mensagem no tópico.
            "acks": "all",
            "enable.idempotence": True,
        }
    )


def publish_run(
    project: str,
    source: str,
    run_id: str,
    started_at: datetime,
    items: list[dict],
    producer=None,
    flush_timeout: float = 30,
) -> int:
    """Publica cada item e, por último, a mensagem de fim de coleta. Falha se algo não for entregue."""
    producer = producer or make_producer(f"airflow-{project}-{source}")
    names = topics(project)
    errors: list[str] = []

    def on_delivery(err, msg):
        if err is not None:
            errors.append(f"{msg.topic()}: {err}")

    now = datetime.now(timezone.utc)
    keys = []
    for item in items:
        key = item_key(source, item)
        keys.append(key)
        producer.produce(
            names["raw"],
            key=key.encode(),
            value=encode(item_message(project, source, run_id, item, now)),
            on_delivery=on_delivery,
        )
        producer.poll(0)
    producer.produce(
        names["runs"],
        key=source.encode(),
        value=encode(run_message(project, source, run_id, started_at, datetime.now(timezone.utc), keys)),
        on_delivery=on_delivery,
    )

    pending = producer.flush(flush_timeout)
    if pending or errors:
        raise RuntimeError(f"Kafka: {pending} mensagens sem confirmação; erros: {errors[:5]}")
    return len(keys)
