"""Tela e API de leitura dos campeonatos (montadas em /bjj/ pelo web/app.py)."""

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.db import connect

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

COLUMNS = """
    id, source, source_event_id, fingerprint, name, edition, start_date, end_date,
    city, state, country, venue, organizer, modality, status, event_url,
    registration_url, registration_deadline, first_seen_at, last_seen_at, removed_at
"""

# Nomes dos campos do histórico, para a tela.
FIELD_LABELS = {
    "name": "nome",
    "edition": "edição",
    "start_date": "início",
    "end_date": "fim",
    "city": "cidade",
    "state": "UF",
    "country": "país",
    "venue": "local",
    "organizer": "organizador",
    "modality": "modalidade",
    "event_url": "página do evento",
    "registration_url": "link de inscrição",
    "registration_deadline": "prazo de inscrição",
    "status": "inscrição",
    "fingerprint": "fingerprint",
    "removed_at": "removido do site em",
}

HISTORY = """
SELECT changed_at, run_id, change_type, field, old_value, new_value
FROM bjj.event_changes WHERE event_id = %(id)s ORDER BY changed_at, id
"""

CHANGES_FEED = """
SELECT c.id, c.changed_at, c.run_id, c.change_type, c.field, c.old_value, c.new_value,
       e.id AS event_id, e.source, e.source_event_id, e.name
FROM bjj.event_changes c JOIN bjj.events e ON e.id = c.event_id
WHERE (%(desde)s::timestamptz IS NULL OR c.changed_at >= %(desde)s)
  AND (%(campo)s::text IS NULL OR c.field = %(campo)s)
ORDER BY c.changed_at, c.id
LIMIT %(limit)s OFFSET %(offset)s
"""


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def build_filters(
    uf: str | None = None,
    status: str | None = None,
    q: str | None = None,
    desde: date | None = None,
    ate: date | None = None,
    passados: bool = False,
    removidos: bool = False,
) -> tuple[str, dict]:
    clauses, params = [], {}
    if not removidos:
        clauses.append("removed_at IS NULL")
    if not passados:
        clauses.append("(COALESCE(end_date, start_date) >= CURRENT_DATE OR start_date IS NULL)")
    if uf:
        clauses.append("state = %(uf)s")
        params["uf"] = uf.strip().upper()
    if status in ("open", "closed"):
        clauses.append("status = %(status)s")
        params["status"] = status
    if q and q.strip():
        clauses.append("name ILIKE %(q)s")
        params["q"] = f"%{q.strip()}%"
    if desde:
        clauses.append("start_date >= %(desde)s")
        params["desde"] = desde
    if ate:
        clauses.append("start_date <= %(ate)s")
        params["ate"] = ate
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def fetch_events(conn, filters: tuple[str, dict], limit: int, offset: int) -> tuple[int, list[dict]]:
    where, params = filters
    total = conn.execute(f"SELECT count(*) AS n FROM bjj.events{where}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM bjj.events{where}"
        " ORDER BY start_date NULLS LAST, name LIMIT %(limit)s OFFSET %(offset)s",
        {**params, "limit": limit, "offset": offset},
    ).fetchall()
    return total, rows


def fetch_stats(conn, filters: tuple[str, dict]) -> dict:
    where, params = filters
    summary = conn.execute(
        "SELECT count(*) AS total, count(*) FILTER (WHERE status = 'open') AS abertos,"
        f" count(DISTINCT state) AS estados FROM bjj.events{where}",
        params,
    ).fetchone()
    por_uf = conn.execute(
        f"SELECT state AS uf, count(*) AS eventos FROM bjj.events{where}"
        " GROUP BY state ORDER BY count(*) DESC, state",
        params,
    ).fetchall()
    por_mes = conn.execute(
        "SELECT to_char(date_trunc('month', start_date), 'YYYY-MM') AS mes, count(*) AS eventos"
        f" FROM bjj.events{where} GROUP BY 1 ORDER BY 1",
        params,
    ).fetchall()
    ultima = conn.execute(
        "SELECT source, max(finished_at) AS ultima_coleta FROM bjj.crawl_runs GROUP BY source ORDER BY source"
    ).fetchall()
    return {**summary, "por_uf": por_uf, "por_mes": por_mes, "ultima_coleta": ultima}


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def page(
    request: Request,
    uf: str | None = None,
    status: str | None = None,
    q: str | None = None,
    desde: str | None = None,
    ate: str | None = None,
    passados: str | None = None,
    removidos: str | None = None,
):
    filters = build_filters(
        uf, status, q, parse_date(desde), parse_date(ate), bool(passados), bool(removidos)
    )
    with connect("bjj") as conn:
        total, events = fetch_events(conn, filters, limit=500, offset=0)
        stats = fetch_stats(conn, filters)
        ufs = [
            r["state"]
            for r in conn.execute(
                "SELECT DISTINCT state FROM bjj.events WHERE state IS NOT NULL ORDER BY state"
            ).fetchall()
        ]
    return templates.TemplateResponse(
        request,
        "bjj.html",
        {
            "events": events,
            "total": total,
            "stats": stats,
            "ufs": ufs,
            "f": {
                "uf": uf or "",
                "status": status or "",
                "q": q or "",
                "desde": desde or "",
                "ate": ate or "",
                "passados": bool(passados),
                "removidos": bool(removidos),
            },
        },
    )


@router.get("/api/eventos", summary="Lista de campeonatos")
def api_events(
    uf: str | None = Query(None, description="Sigla do estado, ex.: SP"),
    status: str | None = Query(None, description="open (inscrição aberta) ou closed"),
    q: str | None = Query(None, description="Trecho do nome"),
    desde: date | None = Query(None, description="Início a partir de (AAAA-MM-DD)"),
    ate: date | None = Query(None, description="Início até (AAAA-MM-DD)"),
    passados: bool = Query(False, description="Incluir eventos que já aconteceram"),
    removidos: bool = Query(False, description="Incluir eventos que sumiram do site"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    with connect("bjj") as conn:
        total, events = fetch_events(
            conn, build_filters(uf, status, q, desde, ate, passados, removidos), limit, offset
        )
    return {"total": total, "limit": limit, "offset": offset, "eventos": events}


@router.get("/api/estatisticas", summary="Totais por estado e por mês")
def api_stats(
    uf: str | None = None,
    status: str | None = None,
    passados: bool = False,
) -> dict:
    with connect("bjj") as conn:
        return fetch_stats(conn, build_filters(uf, status, None, None, None, passados))


def fetch_event_with_history(conn, event_id: int) -> dict | None:
    event = conn.execute(f"SELECT {COLUMNS} FROM bjj.events WHERE id = %(id)s", {"id": event_id}).fetchone()
    if event is None:
        return None
    return {**event, "historico": conn.execute(HISTORY, {"id": event_id}).fetchall()}


@router.get("/eventos/{event_id}", response_class=HTMLResponse, include_in_schema=False)
def event_page(request: Request, event_id: int):
    with connect("bjj") as conn:
        event = fetch_event_with_history(conn, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return templates.TemplateResponse(
        request, "bjj_evento.html", {"e": event, "labels": FIELD_LABELS}
    )


@router.get("/api/eventos/{event_id}", summary="Um campeonato, com todos os campos e o histórico de mudanças")
def api_event(event_id: int) -> dict:
    with connect("bjj") as conn:
        event = fetch_event_with_history(conn, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return event


@router.get("/api/mudancas", summary="Mudanças em todos os campeonatos, da mais antiga para a mais nova")
def api_changes(
    desde: datetime | None = Query(None, description="Só mudanças a partir deste momento (ISO 8601)"),
    campo: str | None = Query(None, description="Só mudanças deste campo, ex.: status"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    with connect("bjj") as conn:
        rows = conn.execute(
            CHANGES_FEED,
            {"desde": desde, "campo": campo, "limit": limit, "offset": offset},
        ).fetchall()
    return {"limit": limit, "offset": offset, "mudancas": rows}
