"""Conexão com o banco de cada projeto e registro das execuções.

Cada projeto tem um banco e um usuário com o seu nome, e a senha em <PROJETO>_DB_PASSWORD.
"""

import os
from datetime import datetime

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

INSERT_RUN = """
INSERT INTO {schema}.crawl_runs (
    run_id, source, started_at, finished_at, pages_fetched, items_found, new_items, errors
) VALUES (%s, %s, %s, now(), %s, %s, %s, %s)
"""


def database_url(project: str) -> str:
    explicit = os.environ.get(f"{project.upper()}_DATABASE_URL")
    if explicit:
        return explicit
    password = os.environ[f"{project.upper()}_DB_PASSWORD"]
    host = os.environ.get("PROJECTS_DB_HOST", "postgres")
    return f"postgresql://{project}:{password}@{host}:5432/{project}"


def connect(project: str | None = None, url: str | None = None) -> psycopg.Connection:
    if url is None:
        if project is None:
            raise ValueError("informe project ou url")
        url = database_url(project)
    return psycopg.connect(url, row_factory=dict_row)


def record_run(
    conn: psycopg.Connection,
    schema: str,
    run_id: str,
    source: str,
    started_at: datetime,
    items_found: int,
    new_items: int,
    pages_fetched: int = 1,
    errors: str | None = None,
) -> None:
    query = sql.SQL(INSERT_RUN).format(schema=sql.Identifier(schema))
    with conn.cursor() as cur:
        cur.execute(
            query,
            (run_id, source, started_at, pages_fetched, items_found, new_items, errors),
        )


def set_run_id(conn: psycopg.Connection, run_id: str) -> None:
    """Identifica a execução da DAG na transação atual (lido por triggers de histórico)."""
    conn.execute("SELECT set_config('crawler.run_id', %s, true)", (run_id,))
