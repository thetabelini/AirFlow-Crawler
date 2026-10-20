import base64

import pytest
from fastapi.testclient import TestClient

from web.app import create_app, parse_users


def _auth(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("WEB_USERS", "felipe:segredo, amigo:outra")
    monkeypatch.setenv("WEB_PUBLIC", "false")
    return TestClient(create_app())


def test_parse_users():
    assert parse_users("a:1, b:2:3,sem-senha,:x,") == {"a": "1", "b": "2:3"}
    assert parse_users("") == {}


def test_health_nao_pede_login(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_sem_login_recebe_401(client):
    response = client.get("/bjj/api/eventos")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


def test_senha_errada_recebe_401(client):
    assert client.get("/bjj/api/eventos", headers=_auth("felipe", "errada")).status_code == 401
    assert client.get("/", headers=_auth("ninguem", "segredo")).status_code == 401


def test_usuario_certo_passa_do_login(client):
    response = client.get("/", headers=_auth("amigo", "outra"), follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/bjj/"


def test_publico_dispensa_login(monkeypatch):
    monkeypatch.setenv("WEB_USERS", "")
    monkeypatch.setenv("WEB_PUBLIC", "true")
    response = TestClient(create_app()).get("/", follow_redirects=False)
    assert response.status_code == 307
