"""Chaves de API, guardadas em web.api_keys só como hash SHA-256.

Criar, listar e revogar: scripts/api-keys.sh.
"""

import hashlib

from web.db import connect


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def check_api_key(key: str) -> str | None:
    """Devolve o nome do dono se a chave estiver ativa, registrando o uso; senão None."""
    with connect("web", read_only=False) as conn:
        row = conn.execute(
            "UPDATE web.api_keys SET last_used_at = now(), requests = requests + 1"
            " WHERE key_hash = %s AND revoked_at IS NULL RETURNING name",
            (hash_key(key),),
        ).fetchone()
    return row["name"] if row else None
