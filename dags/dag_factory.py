"""Gera uma DAG crawl_<fonte> para cada bloco do config/sources.yaml."""

import logging
from datetime import datetime, timedelta, timezone

from airflow.sdk import dag, get_current_context, task

from crawler.sources import Source, load_sources

log = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
}


def build_dag(source: Source):
    @dag(
        dag_id=f"crawl_{source.name}",
        schedule=source.schedule,
        start_date=datetime(2026, 1, 1),
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["crawler", source.name],
    )
    def crawl():
        @task
        def fetch_listing() -> str:
            from crawler.fetch import fetch_html

            return fetch_html(source.url, use_js=source.js)

        @task
        def parse(html: str) -> list[dict]:
            from crawler.parsers import get_parser

            events = get_parser(source.parser)(html)
            if not events:
                raise ValueError(
                    f"nenhum evento encontrado em {source.url}: o layout do site pode ter mudado"
                )
            return events

        @task
        def normalize(raw_events: list[dict]) -> list[dict]:
            from crawler.normalize import normalize_event

            return [normalize_event(source.name, raw) for raw in raw_events]

        @task
        def upsert_notify(events: list[dict]) -> int:
            from crawler import db

            context = get_current_context()
            started_at = context["dag_run"].start_date or datetime.now(timezone.utc)
            with db.connect() as conn:
                new_events = db.upsert_events(conn, events)
                db.record_run(
                    conn,
                    run_id=context["run_id"],
                    source=source.name,
                    started_at=started_at,
                    events_found=len(events),
                    new_events=len(new_events),
                )
            log.info("%s: %d eventos, %d novos", source.name, len(events), len(new_events))
            for event in new_events:
                log.info(
                    "novo: %s | %s | %s - %s",
                    event["name"],
                    event.get("start_date"),
                    event.get("city"),
                    event.get("state"),
                )
            return len(new_events)

        upsert_notify(normalize(parse(fetch_listing())))

    return crawl()


for _source in load_sources():
    globals()[f"crawl_{_source.name}"] = build_dag(_source)
