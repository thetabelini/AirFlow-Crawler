"""Tela e API do BJJ contra o banco real.

Rode com BJJ_TEST_DATABASE_URL=postgresql://bjj:<senha>@localhost:5432/bjj pytest
"""

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from projects.bjj.web import build_filters
from web.app import create_app

DATABASE_URL = os.environ.get("BJJ_TEST_DATABASE_URL")


def test_filtros_padrao_escondem_passados():
    where, params = build_filters()
    assert "CURRENT_DATE" in where and params == {}


def test_filtros_combinados():
    where, params = build_filters(uf=" sp ", status="open", q=" copa ", desde=date(2026, 11, 1))
    assert params == {"uf": "SP", "status": "open", "q": "%copa%", "desde": date(2026, 11, 1)}
    assert where.count(" AND ") == 5
    assert "removed_at IS NULL" in where


def test_status_invalido_e_ignorado():
    _, params = build_filters(status="qualquer", passados=True)
    assert params == {}


def test_removidos_e_passados_liberam_tudo():
    where, params = build_filters(passados=True, removidos=True)
    assert where == "" and params == {}


@pytest.mark.skipif(not DATABASE_URL, reason="BJJ_TEST_DATABASE_URL não definida")
def test_api_e_tela_com_banco(monkeypatch):
    import psycopg

    monkeypatch.setenv("BJJ_WEB_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("WEB_PUBLIC", "true")
    futuro = date.today() + timedelta(days=30)
    passado = date.today() - timedelta(days=30)
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("DELETE FROM bjj.events WHERE source = 'teste_web'")
        for sid, name, start, state, status in [
            ("W1", "ZZTESTE FUTURA SP", futuro, "SP", "open"),
            ("W2", "ZZTESTE FUTURA RJ", futuro, "RJ", "closed"),
            ("W3", "ZZTESTE PASSADA", passado, "SP", "closed"),
        ]:
            conn.execute(
                "INSERT INTO bjj.events (source, source_event_id, fingerprint, name, start_date, end_date, state, status)"
                " VALUES ('teste_web', %s, %s, %s, %s, %s, %s, %s)",
                (sid, sid, name, start, start, state, status),
            )
    try:
        client = TestClient(create_app())
        nomes = lambda r: {e["name"] for e in r.json()["eventos"]}

        r = client.get("/bjj/api/eventos", params={"q": "ZZTESTE FUTURA"})
        assert r.status_code == 200 and nomes(r) == {"ZZTESTE FUTURA SP", "ZZTESTE FUTURA RJ"}
        assert nomes(client.get("/bjj/api/eventos", params={"q": "ZZTESTE", "uf": "sp"})) == {"ZZTESTE FUTURA SP"}
        assert "ZZTESTE PASSADA" in nomes(
            client.get("/bjj/api/eventos", params={"q": "ZZTESTE PASSADA", "passados": "true"})
        )
        assert client.get("/bjj/api/eventos", params={"desde": "nao-e-data"}).status_code == 422

        stats = client.get("/bjj/api/estatisticas").json()
        assert stats["total"] >= 2 and "por_uf" in stats

        page = client.get("/bjj/", params={"q": "ZZTESTE FUTURA", "desde": ""})
        assert page.status_code == 200
        assert "ZZTESTE FUTURA SP" in page.text and "ZZTESTE PASSADA" not in page.text
    finally:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("DELETE FROM bjj.events WHERE source = 'teste_web'")
