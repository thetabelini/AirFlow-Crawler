"""Chaves de API, guardadas em web.api_keys só como hash SHA-256, com limite de uso por chave.

Criar, listar e revogar: scripts/api-keys.sh.
Limites (por chave): WEB_RATE_LIMIT_PER_MINUTE (padrão 60) e WEB_RATE_LIMIT_PER_DAY (padrão 5000).
"""

import hashlib
import os
from dataclasses import dataclass

from web.db import connect

# Numa única ida ao banco: valida a chave, soma o uso total e conta a requisição nas
# janelas do minuto e do dia atuais. As requisições recusadas pelo limite também contam.
CHECK_AND_COUNT = """
WITH k AS (
    UPDATE web.api_keys SET last_used_at = now(), requests = requests + 1
    WHERE key_hash = %(hash)s AND revoked_at IS NULL
    RETURNING id, name
), w AS (
    INSERT INTO web.api_key_usage (key_id, window_kind, window_start, hits)
    SELECT k.id, kind, date_trunc(kind, now()), 1
    FROM k CROSS JOIN (VALUES ('minute'), ('day')) AS kinds (kind)
    ON CONFLICT (key_id, window_kind, window_start)
    DO UPDATE SET hits = web.api_key_usage.hits + 1
    RETURNING window_kind, hits
)
SELECT k.name,
       (SELECT hits FROM w WHERE window_kind = 'minute') AS minute_hits,
       (SELECT hits FROM w WHERE window_kind = 'day') AS day_hits
FROM k
"""

CLEANUP = "DELETE FROM web.api_key_usage WHERE window_start < now() - interval '2 days'"


@dataclass(frozen=True)
class KeyUsage:
    name: str
    minute_hits: int
    day_hits: int


def limits() -> tuple[int, int]:
    return (
        int(os.environ.get("WEB_RATE_LIMIT_PER_MINUTE", "60")),
        int(os.environ.get("WEB_RATE_LIMIT_PER_DAY", "5000")),
    )


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def check_api_key(key: str) -> KeyUsage | None:
    """Se a chave estiver ativa, registra a requisição e devolve o uso atual; senão None."""
    with connect("web", read_only=False) as conn:
        row = conn.execute(CHECK_AND_COUNT, {"hash": hash_key(key)}).fetchone()
        conn.execute(CLEANUP)
    if row is None:
        return None
    return KeyUsage(row["name"], row["minute_hits"], row["day_hits"])
