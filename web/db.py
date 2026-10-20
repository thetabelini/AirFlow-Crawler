"""Conexão com o banco de cada projeto pelo usuário web_reader (só leitura nos projetos)."""

import os

import psycopg
from psycopg.rows import dict_row


def database_url(project: str) -> str:
    explicit = os.environ.get(f"{project.upper()}_WEB_DATABASE_URL")
    if explicit:
        return explicit
    password = os.environ["WEB_DB_PASSWORD"]
    host = os.environ.get("PROJECTS_DB_HOST", "postgres")
    return f"postgresql://web_reader:{password}@{host}:5432/{project}"


def connect(project: str, read_only: bool = True) -> psycopg.Connection:
    return psycopg.connect(
        database_url(project),
        row_factory=dict_row,
        options="-c default_transaction_read_only=on" if read_only else "",
    )
