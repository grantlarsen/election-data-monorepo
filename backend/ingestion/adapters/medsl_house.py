"""Official MEDSL district returns; only the supported 2024 regular general election."""
from datetime import datetime
from pathlib import Path
from uuid import UUID

import polars as pl
from sqlalchemy import Engine

from ingestion import house_returns as house
from ingestion.loader import LoadStats
from ingestion.source import AcquiredFile, DataverseMEDSL
from ingestion.validation import ValidationOutcome


class Job(DataverseMEDSL):
    key = "medsl_house"
    DOI = "doi:10.7910/DVN/IG0UN2"
    METADATA_URL = "https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=" + DOI
    ORIGINAL_FILENAME = "1976-2024-house.tab"
    supported_years = frozenset({2024})
    source_url = "https://doi.org/10.7910/DVN/IG0UN2"
    parse = staticmethod(house.parse)
    normalize = staticmethod(house.normalize)
    select = staticmethod(house.select_regular)

    def validate(self, frame: pl.DataFrame, years: set[int], reference: Path | None) -> ValidationOutcome:
        if reference is not None:
            raise ValueError("House reconciliation is district-specific; --state-totals-csv is unsupported")
        return house.validate(frame, years)

    def load(self, engine: Engine, source_id: UUID, run_id: UUID, asset: AcquiredFile,
             frame: pl.DataFrame, years: set[int], warnings: list[dict],
             started_at: datetime, completed_at: datetime, duration_ms: int, raw_count: int) -> LoadStats:
        from ingestion.loader import load
        return load(engine, source_id, run_id, asset, frame, years, warnings, started_at,
                    completed_at, duration_ms, records_read=raw_count,
                    record_builder=house.records, detail_loader=house.load_details)

    def preview(self, engine: Engine, version: str, sha256: str, years: set[int]) -> dict:
        from ingestion.loader import preview
        return preview(engine, self.key, version, sha256, years)
