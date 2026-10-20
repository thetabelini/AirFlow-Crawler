"""Gera uma DAG <projeto>__<fonte> para cada bloco de projects/<projeto>/sources.yaml."""

import logging
from datetime import datetime, timedelta, timezone

from airflow.sdk import dag, get_current_context, task

from core.projects import Source, load_all_sources

log = logging.getLogger(__name__)


def build_dag(source: Source):
    @dag(
        dag_id=source.dag_id,
        schedule=source.schedule,
        start_date=datetime(2026, 1, 1),
        catchup=False,
        max_active_runs=1,
        default_args={
            "retries": 3,
            "retry_delay": timedelta(minutes=5),
            "retry_exponential_backoff": True,
            # Um pool por projeto (criado pelo airflow-init): um projeto travado não ocupa as vagas dos outros.
            "pool": source.project,
        },
        tags=["crawler", source.project, source.name],
    )
    def crawl():
        @task
        def fetch_listing() -> str:
            from core.fetch import fetch_html

            return fetch_html(source.url, use_js=source.js)

        @task
        def parse(html: str) -> list[dict]:
            from core.projects import get_parser

            items = get_parser(source.project, source.parser)(html)
            if not items:
                raise ValueError(
                    f"nada encontrado em {source.url}: o layout do site pode ter mudado"
                )
            return items

        @task
        def normalize(raw_items: list[dict]) -> list[dict]:
            from core.projects import get_pipeline

            pipeline = get_pipeline(source.project)
            return [pipeline.normalize(source.name, raw) for raw in raw_items]

        @task
        def upsert_notify(items: list[dict]) -> int:
            from core import db
            from core.projects import get_pipeline

            context = get_current_context()
            started_at = context["dag_run"].start_date or datetime.now(timezone.utc)
            with db.connect(source.project) as conn:
                db.set_run_id(conn, context["run_id"])
                new_items = get_pipeline(source.project).store(conn, items)
                db.record_run(
                    conn,
                    schema=source.project,
                    run_id=context["run_id"],
                    source=source.name,
                    started_at=started_at,
                    items_found=len(items),
                    new_items=len(new_items),
                )
            log.info("%s: %d encontrados, %d novos", source.dag_id, len(items), len(new_items))
            for item in new_items:
                log.info("novo: %s", item.get("name") or item)
            return len(new_items)

        upsert_notify(normalize(parse(fetch_listing())))

    return crawl()


for _source in load_all_sources():
    globals()[_source.dag_id] = build_dag(_source)
