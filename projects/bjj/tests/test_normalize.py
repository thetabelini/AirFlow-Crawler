from datetime import date

from core.text import parse_br_date
from projects.bjj.normalize import (
    country_code,
    fingerprint,
    modalities,
    normalize_event,
)


def test_parse_br_date():
    assert parse_br_date("01/11/2026") == date(2026, 11, 1)
    assert parse_br_date("31/02/2026") is None
    assert parse_br_date("") is None


def test_country_code():
    assert country_code("BRASIL") == "BR"
    assert country_code(" br ") == "BR"
    assert country_code("JAPAO") == "JAPAO"
    assert country_code(None) is None


def test_modalities():
    assert modalities("XIV COPA CIDADE DE MANAUS GI E NOGI") == ["gi", "no-gi"]
    assert modalities("CHAMPIONSHIP - GI & NO-GI") == ["gi", "no-gi"]
    assert modalities("AJP TOUR GRAMADO CHAMPIONSHIP GI") == ["gi"]
    assert modalities("COPA SEM KIMONO") == ["no-gi"]
    assert modalities("COPA PRIME #10 ETAPA") == []
    assert modalities("COPA GIGANTE") == []


def test_fingerprint_ignora_acentos_e_caixa():
    assert fingerprint("Copa São Paulo", "2026-11-08", "São Paulo") == fingerprint(
        "COPA SAO PAULO", "2026-11-08", "SAO PAULO"
    )
    assert fingerprint("Copa", "2026-11-08", "Campinas") != fingerprint(
        "Copa", "2026-11-09", "Campinas"
    )


def test_normalize_event():
    event = normalize_event(
        "soucompetidor",
        {
            "source_event_id": " P2866 ",
            "name": "XIV  COPA CIDADE DE MANAUS GI E NOGI",
            "edition": "2026 - EDICAO",
            "start_date": "2026-12-13",
            "end_date": "2026-12-13",
            "city": "MANAUS",
            "state": "am",
            "country": "BRASIL",
        },
    )
    assert event["source"] == "soucompetidor"
    assert event["source_event_id"] == "P2866"
    assert event["name"] == "XIV COPA CIDADE DE MANAUS GI E NOGI"
    assert event["state"] == "AM"
    assert event["country"] == "BR"
    assert event["modality"] == ["gi", "no-gi"]
    assert len(event["fingerprint"]) == 16
