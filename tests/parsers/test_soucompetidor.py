from pathlib import Path

import pytest

from crawler.parsers.soucompetidor import parse

FIXTURE = Path(__file__).parent.parent / "fixtures" / "soucompetidor_inicio.html"


@pytest.fixture(scope="module")
def events():
    return {e["source_event_id"]: e for e in parse(FIXTURE.read_text(encoding="utf-8"))}


def test_ignora_cards_sem_link_de_evento(events):
    assert sorted(events) == [
        "P2574", "P2775", "P2827", "P2835", "P2842", "P2859", "P2864", "P2866",
    ]


def test_evento_com_inscricao_aberta_e_intervalo_de_datas(events):
    assert events["P2842"] == {
        "source_event_id": "P2842",
        "name": "CAMPEONATO GRANDE OESTE DE JIU-JITSU FCJJ 2026",
        "edition": "5 - ETAPA",
        "start_date": "2026-10-31",
        "end_date": "2026-11-01",
        "city": "CHAPECO",
        "state": "SC",
        "country": "BRASIL",
        "venue": None,
        "organizer": None,
        "event_url": "https://soucompetidor.com.br/pt-br/eventos/todos-os-eventos/p2842-campeonato-grande-oeste-de-jiu-jitsu-fcjj-2026-5-etapa/",
        "registration_url": "https://soucompetidor.com.br/pt-br/eventos/inscricao/p2842-campeonato-grande-oeste-de-jiu-jitsu-fcjj-2026-5-etapa/",
        "registration_deadline": None,
        "status": "open",
    }


def test_evento_sem_inscricao_fica_fechado(events):
    for event_id in ("P2775", "P2864"):
        assert events[event_id]["registration_url"] is None
        assert events[event_id]["status"] == "closed"


def test_data_unica_repete_no_fim(events):
    assert events["P2775"]["start_date"] == "2026-10-18"
    assert events["P2775"]["end_date"] == "2026-10-18"


def test_nome_completo_vem_do_alt_e_nao_do_titulo_truncado(events):
    assert events["P2859"]["name"] == (
        "AJP TOUR FLORIANOPOLIS INTERNATIONAL JIU-JITSU CHAMPIONSHIP - GI & NO-GI"
    )
    assert "…" not in events["P2827"]["name"]


def test_espacos_duplicados_no_nome(events):
    assert events["P2866"]["name"] == "XIV COPA CIDADE DE MANAUS GI E NOGI"


def test_cidade_ainda_nao_definida(events):
    assert events["P2574"]["city"] is None
    assert events["P2574"]["state"] == "RS"


def test_pagina_sem_eventos():
    assert parse("<html><body><p>manutenção</p></body></html>") == []
