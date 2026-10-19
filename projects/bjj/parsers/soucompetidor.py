"""Parser da página inicial do Sou Competidor (https://soucompetidor.com.br/pt-br/).

Cada evento é um div.card com:
- link para /eventos/todos-os-eventos/p<id>-<slug>/
- img.card-img-top com alt "P<id>-<NOME COMPLETO> <EDIÇÃO>" (o h6 vem truncado com "…")
- .card-title small: país, "CIDADE - UF", edição, "P<id>"
- .date-badge-card: "dd/mm/aaaa" ou "dd/mm/aaaa - dd/mm/aaaa"
- botão para /eventos/inscricao/... quando as inscrições estão abertas
"""

import re

from selectolax.lexbor import LexborHTMLParser

from core.text import clean, parse_br_date

EVENT_LINK = re.compile(r"/eventos/todos-os-eventos/(p\d+)-[^/]*/?$")
DATE_RANGE = re.compile(r"(\d{2}/\d{2}/\d{4})(?:\s*-\s*(\d{2}/\d{2}/\d{4}))?")


def parse(html: str) -> list[dict]:
    tree = LexborHTMLParser(html)
    events = {}
    for card in tree.css("div.card"):
        event = _parse_card(card)
        if event and event["source_event_id"] not in events:
            events[event["source_event_id"]] = event
    return list(events.values())


def _parse_card(card) -> dict | None:
    link = card.css_first('a[href*="/eventos/todos-os-eventos/p"]')
    if link is None:
        return None
    url = link.attributes.get("href") or ""
    match = EVENT_LINK.search(url)
    if not match:
        return None

    country, location, edition = _title_smalls(card)
    city, state = _split_location(location)
    start_date, end_date = _dates(card)
    registration = card.css_first('a[href*="/eventos/inscricao/"]')
    registration_url = registration.attributes.get("href") if registration else None

    return {
        "source_event_id": match.group(1).upper(),
        "name": _full_name(card, edition),
        "edition": edition,
        "start_date": start_date,
        "end_date": end_date,
        "city": city,
        "state": state,
        "country": country,
        "venue": None,
        "organizer": None,
        "event_url": url,
        "registration_url": registration_url,
        "registration_deadline": None,
        "status": "open" if registration_url else "closed",
    }


def _text(node) -> str | None:
    return clean(node.text()) if node is not None else None


def _title_smalls(card) -> tuple[str | None, str | None, str | None]:
    country = _text(card.css_first(".card-title small span"))
    edition = _text(card.css_first(".card-title .text-edicao"))
    location = None
    for small in card.css(".card-title small"):
        text = _text(small)
        if text and text != country and text != edition and " - " in text:
            location = text
            break
    return country, location, edition


def _split_location(location: str | None) -> tuple[str | None, str | None]:
    if not location:
        return None, None
    city, _, state = location.rpartition(" - ")
    if not city:
        return clean(location), None
    if "EM BREVE" in city.upper():
        city = None
    return clean(city), clean(state)


def _dates(card) -> tuple[str | None, str | None]:
    match = DATE_RANGE.search(_text(card.css_first(".date-badge-card")) or "")
    if not match:
        return None, None
    start = parse_br_date(match.group(1))
    end = parse_br_date(match.group(2)) if match.group(2) else start
    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
    )


def _full_name(card, edition: str | None) -> str | None:
    img = card.css_first("img.card-img-top")
    alt = clean(img.attributes.get("alt")) if img is not None else None
    if alt:
        alt = re.sub(r"^P\d+-", "", alt)
        if edition and alt.endswith(edition):
            alt = alt[: -len(edition)]
        alt = clean(alt)
    return alt or _text(card.css_first("h6"))
