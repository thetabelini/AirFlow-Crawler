"""O que o gerador de DAGs chama depois do parser: normalize() e store()."""

from projects.bjj.normalize import normalize_event as normalize
from projects.bjj.store import upsert_events as store

__all__ = ["normalize", "store"]
