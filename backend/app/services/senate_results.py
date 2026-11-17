"""Senate daily refresh and profile synchronization over the shared results cache."""
import asyncio
import logging

from ingestion import current_senate as source
from app.services.current_results import ResultsCache

LOG = logging.getLogger(__name__)
_cache = ResultsCache(source, "SENATE_RESULTS_CACHE_DIR", "data/ingestion/current_senate")
cache_directory = _cache.cache_directory
read_snapshot = _cache.read_snapshot
refresh_snapshot = _cache.refresh_snapshot


async def daily_refresh() -> None:
    """Refresh on startup when due, then check hourly; failures retry in one hour."""
    while True:
        try:
            await asyncio.to_thread(refresh_snapshot)
            from app.services.senate_entities import sync_cached_entities
            await asyncio.to_thread(sync_cached_entities)
        except Exception:
            # Never stop the API; include lock/filesystem failures in the log too.
            LOG.warning("Daily Senate refresh will retry in one hour")
        await asyncio.sleep(3600)
