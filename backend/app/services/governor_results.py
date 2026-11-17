"""Daily provisional Governor results using the durable shared cache."""
import asyncio
import logging

from ingestion import current_governor as source
from app.services.current_results import ResultsCache

LOG = logging.getLogger(__name__)
_cache = ResultsCache(source, "GOVERNOR_RESULTS_CACHE_DIR", "data/ingestion/current_governor")
cache_directory = _cache.cache_directory
read_snapshot = _cache.read_snapshot
refresh_snapshot = _cache.refresh_snapshot


async def daily_refresh() -> None:
    """Refresh when due on startup and hourly; retry failures in one hour."""
    while True:
        try:
            await asyncio.to_thread(refresh_snapshot)
            from app.services.governor_entities import sync_cached_entities
            await asyncio.to_thread(sync_cached_entities)
        except Exception:
            LOG.warning("Daily Governor refresh will retry in one hour")
        await asyncio.sleep(3600)
