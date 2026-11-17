"""Daily House cache and explicit source-winner seat accounting."""
import asyncio
import logging

from ingestion import current_house as source
from app.services.current_results import ResultsCache

LOG = logging.getLogger(__name__)
_cache = ResultsCache(source, "HOUSE_RESULTS_CACHE_DIR", "data/ingestion/current_house")
cache_directory = _cache.cache_directory
read_snapshot = _cache.read_snapshot
refresh_snapshot = _cache.refresh_snapshot


def house_control(snapshot: dict) -> dict:
    """A lead never earns a seat; missing contests remain unresolved."""
    called = {"D": 0, "R": 0, "other": 0}
    seen = set()
    for race in snapshot["races"]:
        if race["id"] not in source.EXPECTED_CONTESTS or race["id"] in seen:
            raise source.ResultsSourceError("Invalid House control scope")
        seen.add(race["id"])
        if race["status"] not in {"called", "final"}:
            continue
        winners = [c for c in race["candidates"] if c["outcome"] == "won"]
        if len(winners) != 1:
            raise source.ResultsSourceError("House call has no unique source winner")
        party = winners[0]["party"]
        called[party if party in {"D", "R"} else "other"] += 1
    return {"total_seats": 435, "majority_threshold": 218, "called": called,
            "unresolved": 435 - sum(called.values()),
            "control": next((party for party in ("D", "R") if called[party] >= 218), None)}


async def daily_refresh() -> None:
    """On startup and hourly thereafter, refresh when the daily cache is due."""
    while True:
        try:
            await asyncio.to_thread(refresh_snapshot)
            from app.services.house_entities import sync_cached_entities
            await asyncio.to_thread(sync_cached_entities)
        except Exception:
            LOG.warning("Daily House refresh will retry in one hour")
        await asyncio.sleep(3600)
