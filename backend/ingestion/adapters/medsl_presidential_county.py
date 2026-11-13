"""MEDSL adapter: transforms official data into generic lossless result observations."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import polars as pl
from sqlalchemy import Engine

from ingestion.medsl import YEARS, normalize, parse_csv
from ingestion.source import DataverseMEDSL, AcquiredFile
from ingestion.validation import ValidationOutcome, validate


class Job(DataverseMEDSL):
    supported_years = YEARS
    source_url = "https://doi.org/10.7910/DVN/VOQCHQ"

    def parse(self, path: Path) -> pl.DataFrame:
        return parse_csv(str(path))

    def normalize(self, frame: pl.DataFrame) -> pl.DataFrame:
        return normalize(frame)

    def select(self, frame: pl.DataFrame, years: set[int]) -> pl.DataFrame:
        # Include malformed years for rejection instead of silently filtering them away.
        return frame.filter(pl.col("year_int").is_in(sorted(years)) |
                            pl.col("year_int").is_null() |
                            ~pl.col("year_int").is_in(sorted(YEARS)))

    def validate(self, frame: pl.DataFrame, years: set[int], reference: Path | None) -> ValidationOutcome:
        return validate(frame, years, state_totals_csv=reference)

    def load(self, engine: Engine, source_id: UUID, run_id: UUID, asset: AcquiredFile,
             frame: pl.DataFrame, years: set[int], warnings: list[dict],
             started_at: Any, completed_at: Any, duration_ms: int, raw_count: int) -> Any:
        from ingestion.loader import load
        return load(engine, source_id, run_id, asset, frame, years, warnings,
                    started_at, completed_at, duration_ms, records_read=raw_count)

    def preview(self, engine: Engine, version: str, sha256: str, years: set[int]) -> dict:
        from ingestion.loader import preview
        return preview(engine, self.key, version, sha256, years)
