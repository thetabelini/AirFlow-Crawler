"""Um módulo por site. Cada um expõe parse(html) -> list[dict] com os campos de RawEvent."""

import importlib
from collections.abc import Callable


def get_parser(name: str) -> Callable[[str], list[dict]]:
    if not name.isidentifier():
        raise ValueError(f"nome de parser inválido: {name!r}")
    return importlib.import_module(f"crawler.parsers.{name}").parse
