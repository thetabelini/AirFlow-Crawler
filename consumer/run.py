"""Consumidor do Kafka: grava no banco de cada projeto o que as DAGs publicaram.

Lê <projeto>.events.raw e <projeto>.runs de todo projeto que tem projects/<nome>/consumer.py,
num grupo só (KAFKA_CONSUMER_GROUP, padrão "store"). Para cada mensagem:

1. valida e grava numa transação (handle_item / handle_run do projeto);
2. só depois do commit no banco, faz o commit do offset no Kafka.

Mensagem que nunca vai poder ser gravada (stream.InvalidMessage, ou o banco recusou os dados)
vai para <projeto>.events.dlq com o motivo, e o consumidor segue.
Qualquer outro erro (banco ou Kafka fora do ar) derruba o processo sem o commit do offset:
o Docker o reinicia e a mensagem é lida de novo. Por isso o mesmo item pode chegar mais de uma
vez, e cada projeto precisa reconhecer o que já gravou.
"""

import importlib
import logging
import os
import signal
from types import ModuleType

import psycopg
from confluent_kafka import Consumer, KafkaException

from core import db, stream
from core.projects import list_projects

log = logging.getLogger("consumer")


def load_handlers() -> dict[str, ModuleType]:
    handlers = {}
    for project in list_projects():
        name = f"projects.{project}.consumer"
        try:
            handlers[project] = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
    return handlers


def connect(project: str) -> psycopg.Connection:
    # autocommit: cada mensagem abre a própria transação com conn.transaction().
    conn = db.connect(project)
    conn.autocommit = True
    return conn


class Runner:
    def __init__(self, handlers: dict[str, ModuleType], consumer, producer, conns: dict):
        self.handlers = handlers
        self.consumer = consumer
        self.producer = producer
        self.conns = conns
        self.routes = {}
        for project in handlers:
            names = stream.topics(project)
            self.routes[names["raw"]] = (project, "item")
            self.routes[names["runs"]] = (project, "run_finished")

    def process(self, msg) -> str:
        """Aplica uma mensagem e devolve o que aconteceu com ela (para o log)."""
        project, kind = self.routes[msg.topic()]
        handler = self.handlers[project]
        conn = self.conns[project]
        try:
            message = stream.decode(msg.value())
            stream.check(message, project, kind)
            with conn.transaction():
                if kind == "item":
                    return handler.handle_item(conn, message)
                return handler.handle_run(conn, message)
        except (stream.InvalidMessage, psycopg.DataError, psycopg.IntegrityError) as exc:
            self.reject(project, msg, f"{type(exc).__name__}: {exc}")
            return f"rejeitada, enviada para {stream.topics(project)['dlq']}: {exc}"

    def reject(self, project: str, msg, error: str) -> None:
        errors = []
        self.producer.produce(
            stream.topics(project)["dlq"],
            key=msg.key(),
            value=stream.encode(
                stream.dlq_message(msg.topic(), msg.partition(), msg.offset(), msg.value(), error)
            ),
            on_delivery=lambda err, _: err and errors.append(err),
        )
        if self.producer.flush(10) or errors:
            raise RuntimeError(f"não consegui gravar na DLQ: {errors or 'sem confirmação'}")

    def handle(self, msg) -> None:
        result = self.process(msg)
        key = msg.key().decode(errors="replace") if msg.key() else "-"
        log.info("%s[%d]@%d %s: %s", msg.topic(), msg.partition(), msg.offset(), key, result)
        # Depois do commit no banco (ou da DLQ). Se o processo cair antes desta linha,
        # a mensagem volta na próxima leitura e cai em "repetida".
        self.consumer.commit(message=msg, asynchronous=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    handlers = load_handlers()
    if not handlers:
        raise SystemExit("nenhum projeto com consumer.py")

    consumer = Consumer(
        {
            "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            "group.id": os.environ.get("KAFKA_CONSUMER_GROUP", "store"),
            # Grupo novo começa do início do tópico (o que ainda está na retenção).
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    runner = Runner(
        handlers,
        consumer,
        stream.make_producer("consumer-dlq"),
        {project: connect(project) for project in handlers},
    )

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    consumer.subscribe(sorted(runner.routes))
    log.info("lendo %s", ", ".join(sorted(runner.routes)))
    try:
        while running:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().fatal():
                    raise KafkaException(msg.error())
                log.warning("kafka: %s", msg.error())
                continue
            runner.handle(msg)
    finally:
        consumer.close()
        for conn in runner.conns.values():
            conn.close()
        log.info("parado")


if __name__ == "__main__":
    main()
