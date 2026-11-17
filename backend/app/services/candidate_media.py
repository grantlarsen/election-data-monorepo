"""Reviewed source-candidacy media, independent of canonical person/FEC matching."""
from copy import deepcopy
from functools import lru_cache

from ingestion.candidate_portraits import read_catalogs


@lru_cache(maxsize=1)
def portrait_catalog() -> dict:
    catalog = read_catalogs()
    return {(row["source"], row["year"], row["race_id"], row["name"], row["party"]): row["portrait"]
            for row in catalog["candidates"]}


def candidate_portrait(source: str, year: int, race_id: str, name: str, party: str) -> dict | None:
    return deepcopy(portrait_catalog().get((source, year, race_id, name, party)))
