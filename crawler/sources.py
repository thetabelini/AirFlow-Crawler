"""Leitura do config/sources.yaml: um bloco por site."""

import os
from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    parser: str
    schedule: str = "@daily"
    js: bool = False


def load_sources(path: str | None = None) -> list[Source]:
    path = path or os.environ.get("BJJ_SOURCES_FILE", "config/sources.yaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return [Source(**item) for item in data]
