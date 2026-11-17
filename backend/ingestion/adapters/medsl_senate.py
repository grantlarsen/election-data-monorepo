"""MEDSL statewide Senate source, calendar years 2000–2024 (including 2021 runoffs)."""
from datetime import datetime
from pathlib import Path
from uuid import UUID

import polars as pl
from sqlalchemy import Engine

from ingestion import senate_returns as senate
from ingestion.loader import LoadStats
from ingestion.source import AcquiredFile, DataverseMEDSL
from ingestion.validation import ValidationOutcome


class Job(DataverseMEDSL):
    key = "medsl_senate"
    DOI = "doi:10.7910/DVN/PEJ5QU"
    METADATA_URL = "https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=" + DOI
    ORIGINAL_FILENAME = "1976-2024-senate-state.csv"
    supported_years = senate.YEARS
    source_url = "https://doi.org/10.7910/DVN/PEJ5QU"
    parse = staticmethod(senate.parse)
    normalize = staticmethod(senate.normalize)
    select = staticmethod(senate.select_years)

    def validate(self, frame: pl.DataFrame, years: set[int], reference: Path | None) -> ValidationOutcome:
        if reference is not None:
            raise ValueError("Senate reconciliation is contest-specific; --state-totals-csv is unsupported")
        return senate.validate(frame, years)

    def load(self, engine: Engine, source_id: UUID, run_id: UUID, asset: AcquiredFile,
             frame: pl.DataFrame, years: set[int], warnings: list[dict],
             started_at: datetime, completed_at: datetime, duration_ms: int, raw_count: int) -> LoadStats:
        from ingestion.loader import load
        return load(engine, source_id, run_id, asset, frame, years, warnings, started_at,
                    completed_at, duration_ms, records_read=raw_count,
                    record_builder=senate.records, detail_loader=senate.load_details)

    def preview(self, engine: Engine, version: str, sha256: str, years: set[int]) -> dict:
        from ingestion.loader import preview
        return preview(engine, self.key, version, sha256, years)
