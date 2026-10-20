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


@pytest.fixture
def chaves(monkeypatch):
    """Simula web.api_keys: só a chave "afc_boa" é válida, e registra cada consulta."""
    from web import apikeys

    usadas = []

    def check(key):
        usadas.append(key)
        return apikeys.KeyUsage("joao", minute_hits=1, day_hits=1) if key == "afc_boa" else None

    monkeypatch.setattr(apikeys, "check_api_key", check)
    return usadas


def test_chave_valida_libera_a_api(client, chaves):
    response = client.get("/", headers={"X-API-Key": "afc_boa"}, follow_redirects=False)
    assert response.status_code == 307
    assert chaves == ["afc_boa"]


def test_chave_invalida_recebe_401_mesmo_com_senha_certa(client, chaves):
    headers = {"X-API-Key": "afc_errada", **_auth("felipe", "segredo")}
    response = client.get("/bjj/api/eventos", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Chave de API inválida ou revogada"


def test_sem_chave_continua_aceitando_usuario_e_senha(client, chaves):
    response = client.get("/", headers=_auth("felipe", "segredo"), follow_redirects=False)
    assert response.status_code == 307
    assert chaves == []


def test_docs_mostra_a_chave_como_forma_de_autenticacao(client):
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert schemes["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Chave de API recebida do administrador",
    }


def test_hash_da_chave_e_sha256_hex():
    import hashlib

    from web.apikeys import hash_key

    assert hash_key("afc_teste") == hashlib.sha256(b"afc_teste").hexdigest()


@pytest.fixture
def uso(monkeypatch):
    """Chave "afc_boa" válida, com o uso da janela atual definido pelo teste."""
    from web import apikeys

    atual = {"minute": 1, "day": 1}
    monkeypatch.setenv("WEB_RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.setenv("WEB_RATE_LIMIT_PER_DAY", "10")
    monkeypatch.setattr(
        apikeys,
        "check_api_key",
        lambda key: apikeys.KeyUsage("joao", atual["minute"], atual["day"]) if key == "afc_boa" else None,
    )
    return atual


def test_resposta_traz_o_que_resta_do_limite(client, uso, monkeypatch):
    monkeypatch.setattr("projects.bjj.web.connect", _banco_vazio)
    uso.update(minute=2, day=7)
    response = client.get("/bjj/api/eventos", headers={"X-API-Key": "afc_boa"})
    assert response.status_code == 200
    assert response.headers["x-ratelimit-remaining-minute"] == "1"
    assert response.headers["x-ratelimit-remaining-day"] == "3"
    assert response.headers["x-ratelimit-limit-minute"] == "3"


def test_passou_do_limite_por_minuto(client, uso):
    uso.update(minute=4, day=4)
    response = client.get("/bjj/api/eventos", headers={"X-API-Key": "afc_boa"})
    assert response.status_code == 429
    assert "por minuto" in response.json()["detail"]
    assert 1 <= int(response.headers["retry-after"]) <= 61


def test_passou_do_limite_por_dia(client, uso):
    uso.update(minute=1, day=11)
    response = client.get("/bjj/api/eventos", headers={"X-API-Key": "afc_boa"})
    assert response.status_code == 429
    assert "por dia" in response.json()["detail"]
    assert int(response.headers["retry-after"]) <= 86401


def test_usuario_e_senha_nao_tem_limite(client, uso, monkeypatch):
    monkeypatch.setattr("projects.bjj.web.connect", _banco_vazio)
    uso.update(minute=999, day=999)
    response = client.get("/bjj/api/eventos", headers=_auth("felipe", "segredo"))
    assert response.status_code == 200
    assert "x-ratelimit-remaining-minute" not in response.headers


def test_segundos_ate_a_proxima_janela():
    from datetime import datetime, timezone

    from web.app import seconds_until_next

    agora = datetime(2026, 10, 20, 23, 59, 30, tzinfo=timezone.utc)
    assert seconds_until_next("minute", agora) == 31
    assert seconds_until_next("day", agora) == 31
    assert seconds_until_next("day", datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)) == 86401


class _Vazio:
    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return {"n": 0}

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _banco_vazio(project):
    return _Vazio()
