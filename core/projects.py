"""Descoberta dos projetos em projects/ e leitura do sources.yaml de cada um.

Um projeto é uma pasta projects/<nome>/ com:
- sources.yaml: um bloco por site
- parsers/<parser>.py: parse(html) -> list[dict]
- pipeline.py: normalize(source, raw) -> dict e store(conn, items) -> list[dict] (os novos)
- consumer.py (opcional): handle_item e handle_run, usados pelo consumidor do Kafka
- sql/: migrações do banco <nome>
"""

import importlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import yaml

NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Source:
    project: str
    name: str
    url: str
    parser: str
    schedule: str = "@daily"
    js: bool = False

    @property
    def dag_id(self) -> str:
        return f"{self.project}__{self.name}"


def projects_dir() -> Path:
    default = Path(__file__).resolve().parent.parent / "projects"
    return Path(os.environ.get("PROJECTS_DIR", default))


def list_projects() -> list[str]:
    return sorted(
        path.parent.name
        for path in projects_dir().glob("*/sources.yaml")
        if NAME.match(path.parent.name)
    )


def load_sources(project: str) -> list[Source]:
    with open(projects_dir() / project / "sources.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    sources = [Source(project=project, **item) for item in data]
    for source in sources:
        if not NAME.match(source.name) or not NAME.match(source.parser):
            raise ValueError(f"{project}: nome inválido em sources.yaml: {source}")
    return sources


def load_all_sources() -> list[Source]:
    return [source for project in list_projects() for source in load_sources(project)]


def get_pipeline(project: str) -> ModuleType:
    _check_name(project)
    return importlib.import_module(f"projects.{project}.pipeline")


def get_parser(project: str, parser: str) -> Callable[[str], list[dict]]:
    _check_name(project)
    _check_name(parser)
    return importlib.import_module(f"projects.{project}.parsers.{parser}").parse


def _check_name(name: str) -> None:
    if not NAME.match(name):
        raise ValueError(f"nome inválido: {name!r}")
