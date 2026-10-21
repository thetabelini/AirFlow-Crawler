"""O que o consumidor do Kafka (consumer/run.py) faz com as mensagens do projeto bjj.

handle_item: um evento de bjj.events.raw. Antes de gravar, confere se é repetido:
  repetida  produced_at igual ou anterior ao da última mensagem aplicada ao evento: o Kafka
            entregou de novo, ou o consumidor está relendo o tópico. Nada é gravado.
  igual     mensagem nova, mas os campos são os mesmos do banco: só atualiza last_seen_at,
            sem linha no histórico.
  novo / alterado / voltou ao site
            grava com o mesmo upsert da DAG; o trigger registra o que mudou.

handle_run: um fim de coleta de bjj.runs. Marca como removidos os eventos da fonte que não
estão na lista de chaves e registra a execução em bjj.crawl_runs.

As duas rodam dentro de uma transação aberta pelo consumidor, que só faz o commit do offset
depois do commit no banco. Mensagem que não dá para gravar levanta stream.InvalidMessage e vai
para bjj.events.dlq.
"""

import json
from datetime import date

import psycopg

from core import db, stream
from projects.bjj.store import EVENT_DEFAULTS, upsert_events

STATUSES = {"open", "closed", "cancelled"}
DATE_FIELDS = ("start_date", "end_date", "registration_deadline")
# Campos comparados para decidir se o evento mudou (os mesmos que o upsert grava).
COMPARED = ("fingerprint", "name", *EVENT_DEFAULTS)

CURRENT = f"""
SELECT id, removed_at, last_produced_at, {", ".join(COMPARED)}
FROM bjj.events WHERE source = %s AND source_event_id = %s
FOR UPDATE
"""

TOUCH = """
UPDATE bjj.events SET last_seen_at = now(), last_produced_at = %(produced_at)s
WHERE id = %(id)s
"""

SET_PRODUCED_AT = """
UPDATE bjj.events SET last_produced_at = %(produced_at)s
WHERE source = %(source)s AND source_event_id = %(source_event_id)s
"""

LAST_RUN = """
SELECT run_id, started_at FROM bjj.crawl_runs
WHERE source = %s ORDER BY started_at DESC, id DESC LIMIT 1
"""

RUN_EXISTS = "SELECT 1 FROM bjj.crawl_runs WHERE source = %s AND run_id = %s"

MARK_REMOVED = """
UPDATE bjj.events SET removed_at = now()
WHERE source = %(source)s AND removed_at IS NULL AND NOT (source_event_id = ANY(%(ids)s))
RETURNING source_event_id, name
"""

NEW_IN_RUN = """
SELECT count(*) AS n FROM bjj.event_changes c JOIN bjj.events e ON e.id = c.event_id
WHERE c.run_id = %s AND c.change_type = 'created' AND e.source = %s
"""


def _comparable(values: dict) -> dict:
    """Os campos comparados, com datas em texto, como chegam no JSON."""
    return json.loads(stream.encode({field: values[field] for field in COMPARED}))


def validate_item(message: dict) -> dict:
    item = message.get("item")
    if not isinstance(item, dict):
        raise stream.InvalidMessage("sem o objeto item")
    item = {**EVENT_DEFAULTS, **item}
    for field in ("source", "source_event_id", "fingerprint", "name"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise stream.InvalidMessage(f"campo obrigatório vazio: {field}")
    if item["source"] != message.get("source"):
        raise stream.InvalidMessage(f"item da fonte {item['source']!r} na mensagem de {message.get('source')!r}")
    if item["status"] not in STATUSES:
        raise stream.InvalidMessage(f"status desconhecido: {item['status']!r}")
    for field in DATE_FIELDS:
        if item[field] is not None:
            try:
                date.fromisoformat(item[field])
            except (TypeError, ValueError):
                raise stream.InvalidMessage(f"{field} não é uma data: {item[field]!r}") from None
    if not isinstance(item["modality"], list) or not all(isinstance(m, str) for m in item["modality"]):
        raise stream.InvalidMessage(f"modality não é uma lista de textos: {item['modality']!r}")
    return item


def handle_item(conn: psycopg.Connection, message: dict) -> str:
    item = validate_item(message)
    produced_at = stream.parse_time(message, "produced_at")

    current = conn.execute(CURRENT, (item["source"], item["source_event_id"])).fetchone()
    if current and current["last_produced_at"] and produced_at <= current["last_produced_at"]:
        return "repetida"

    if current and current["removed_at"] is None:
        old, new = _comparable(current), _comparable(item)
        if old == new:
            conn.execute(TOUCH, {"id": current["id"], "produced_at": produced_at})
            return "igual"
        changed = [field for field in COMPARED if old[field] != new[field]]
        result = f"alterado ({', '.join(changed)})"
    else:
        result = "voltou ao site" if current else "novo"

    db.set_run_id(conn, message["run_id"])
    upsert_events(conn, [item])
    conn.execute(SET_PRODUCED_AT, {**item, "produced_at": produced_at})
    return result


def handle_run(conn: psycopg.Connection, message: dict) -> str:
    source, run_id, keys = message.get("source"), message.get("run_id"), message.get("keys")
    if not isinstance(source, str) or not isinstance(run_id, str) or not isinstance(keys, list):
        raise stream.InvalidMessage("run_finished sem source, run_id ou keys")
    prefix = f"{source}:"
    if not all(isinstance(key, str) and key.startswith(prefix) for key in keys):
        raise stream.InvalidMessage(f"chave fora do formato {prefix}<id>")
    if not keys:
        # A DAG falha antes de publicar uma coleta vazia. Se uma chegar, não removemos tudo.
        raise stream.InvalidMessage("coleta sem nenhum item")
    started_at = stream.parse_time(message, "started_at")

    if conn.execute(RUN_EXISTS, (source, run_id)).fetchone():
        return "repetida"
    last = conn.execute(LAST_RUN, (source,)).fetchone()
    if last and last["started_at"] > started_at:
        return f"antiga (já há a coleta {last['run_id']})"

    db.set_run_id(conn, run_id)
    ids = [key[len(prefix):] for key in keys]
    removed = conn.execute(MARK_REMOVED, {"source": source, "ids": ids}).fetchall()
    # Conta os criados por esta coleta que o consumidor já gravou. Os itens e o fim da coleta
    # estão em tópicos diferentes: se algum item chegar depois, ele não entra na conta.
    new_items = conn.execute(NEW_IN_RUN, (run_id, source)).fetchone()["n"]
    db.record_run(
        conn, "bjj", run_id, source, started_at, items_found=len(keys), new_items=new_items
    )
    names = ", ".join(r["name"] for r in removed)
    return f"{len(keys)} itens, {new_items} novos, {len(removed)} removidos" + (
        f": {names}" if names else ""
    )

