"""Tela e API de leitura dos campeonatos (montadas em /bjj/ pelo web/app.py)."""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.db import connect

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

COLUMNS = """
    source, source_event_id, name, edition, start_date, end_date, city, state, country,
    modality, status, event_url, registration_url, first_seen_at, last_seen_at
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
) -> tuple[str, dict]:
    clauses, params = [], {}
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
):
    filters = build_filters(uf, status, q, parse_date(desde), parse_date(ate), bool(passados))
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
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    with connect("bjj") as conn:
        total, events = fetch_events(
            conn, build_filters(uf, status, q, desde, ate, passados), limit, offset
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
