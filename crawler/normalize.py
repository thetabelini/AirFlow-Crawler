"""Limpeza comum a todas as fontes e campos derivados (país, modalidade, fingerprint)."""

import hashlib
import re
import unicodedata
from datetime import date, datetime

COUNTRY_CODES = {
    "BRASIL": "BR",
    "BRAZIL": "BR",
    "ARGENTINA": "AR",
    "PARAGUAI": "PY",
    "URUGUAI": "UY",
    "CHILE": "CL",
    "PORTUGAL": "PT",
    "ESTADOS UNIDOS": "US",
    "USA": "US",
}

NOGI = re.compile(r"\bNO[\s-]?GI\b|\bSEM KIMONO\b")
GI = re.compile(r"\bGI\b|\bCOM KIMONO\b|\bKIMONO\b")

TEXT_FIELDS = (
    "source_event_id",
    "name",
    "edition",
    "city",
    "venue",
    "organizer",
    "event_url",
    "registration_url",
)


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def parse_br_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def slug(value: str | None) -> str:
    if not value:
        return ""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def country_code(value: str | None) -> str | None:
    value = clean(value)
    if not value:
        return None
    upper = value.upper()
    if len(upper) == 2:
        return upper
    return COUNTRY_CODES.get(upper, value)


def modalities(*texts: str | None) -> list[str]:
    text = " ".join(t for t in texts if t).upper()
    found = []
    if GI.search(NOGI.sub(" ", text)):
        found.append("gi")
    if NOGI.search(text):
        found.append("no-gi")
    return found


def fingerprint(name: str | None, start_date: str | None, city: str | None) -> str:
    key = f"{slug(name)}|{start_date or ''}|{slug(city)}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def normalize_event(source: str, raw: dict) -> dict:
    event = dict(raw)
    for field in TEXT_FIELDS:
        event[field] = clean(event.get(field))
    state = clean(event.get("state"))
    event["state"] = state.upper() if state else None
    event["country"] = country_code(event.get("country"))
    event["modality"] = modalities(event["name"], event["edition"])
    event["source"] = source
    event["fingerprint"] = fingerprint(event["name"], event.get("start_date"), event["city"])
    return event
