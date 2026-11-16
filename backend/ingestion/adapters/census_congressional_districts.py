"""Census 2024 Gazetteer identifiers for the 119th Congress; no geometry claims."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4, uuid5
from zipfile import ZipFile

import polars as pl
from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.core import DataSource, Jurisdiction
from app.models.geography import GeographicReference, JurisdictionIdentifier, JurisdictionRelationship
from app.models.ingestion import IngestionRun, SourceRelease
from ingestion.geography.load import stable_jurisdiction_id, JURISDICTION_NS, REFERENCE_NS
from ingestion.loader import _chunks
from ingestion.medsl import STATE_FIPS, STATE_NAMES
from ingestion.source import AcquiredFile, SourceInfo

SOURCE_PAGE = "https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2024.html"
URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_119CDs_national.zip"


class Job:
    key = "census_congressional_districts"
    geographic_reference = True
    supported_vintages = frozenset({2024})
    source_url = SOURCE_PAGE

    def __init__(self, vintage: int | None = None):
        self.vintage = vintage

    @property
    def range(self) -> tuple[int, int]:
        return (2024, 2024)

    def describe(self) -> SourceInfo:
        if self.vintage != 2024:
            raise ValueError("Congressional district reference requires --vintage 2024")
        return SourceInfo(self.key, "Census 2024 Gazetteer 119th Congress", "2024-119", 2024,
            "2024_Gaz_119CDs_national.zip", URL, None, None,
            dict(provider="U.S. Census Bureau", congress=119, vintage_start=2024, vintage_end=2024,
                 source_page=SOURCE_PAGE, vintage_semantics="2024 election reference; no legal effective dates inferred"))

    def parse(self, path: Path) -> pl.DataFrame:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if names != ["2024_Gaz_119CDs_national.txt"]:
                raise ValueError("Unexpected congressional Gazetteer archive members")
            frame = pl.read_csv(archive.read(names[0]), separator="\t", infer_schema_length=0)
        if not {"USPS", "GEOID"} <= set(frame.columns):
            raise ValueError("Census district file lacks USPS/GEOID")
        return frame.select(pl.col("USPS").str.strip_chars().alias("state_code"),
                            pl.col("GEOID").str.strip_chars().alias("geoid")).with_row_index("source_row_number", offset=2)

    def validate(self, frame: pl.DataFrame) -> dict:
        valid_codes = {**STATE_FIPS, "PR":"72"}
        invalid = frame.filter(~pl.col("geoid").str.contains(r"^[0-9]{2}([0-9]{2}|ZZ)$") |
            (pl.col("geoid").str.slice(0, 2) != pl.col("state_code").replace_strict(valid_codes, default="")) |
            pl.col("state_code").is_null() | pl.col("geoid").is_null())
        selected = frame.filter(pl.col("state_code").is_in(list(STATE_FIPS)) & ~pl.col("geoid").str.ends_with("ZZ"))
        if invalid.height or frame.get_column("geoid").n_unique() != frame.height:
            raise ValueError("Malformed or duplicate Census district identifiers")
        if selected.height != 436 or selected.get_column("state_code").n_unique() != 51:
            raise ValueError("Expected 435 voting districts and DC in Census reference")
        if selected.filter(pl.col("state_code") == "DC").get_column("geoid").to_list() != ["1198"]:
            raise ValueError("DC must use Census nonvoting-delegate code 98")
        return dict(records_in_file=frame.height, district_rows=selected.height,
                    excluded_outside_50_states_dc=frame.filter(~pl.col("state_code").is_in(list(STATE_FIPS))).height,
                    excluded_undefined_districts=frame.filter(pl.col("geoid").str.ends_with("ZZ")).height)

    def load(self, engine: Engine, source_id: UUID, run_id: UUID, asset: AcquiredFile,
             frame: pl.DataFrame, validation: dict, *, started_at: datetime | None = None) -> dict:
        frame = frame.filter(pl.col("state_code").is_in(list(STATE_FIPS)) & ~pl.col("geoid").str.ends_with("ZZ"))
        with engine.begin() as conn:
            conn.execute(select(DataSource.id).where(DataSource.id == source_id).with_for_update()).scalar_one()
            info = asset.info
            conn.execute(pg_insert(SourceRelease).values(id=uuid4(), source_id=source_id,
                version=info.version, sha256=asset.sha256, filename=info.filename, file_id=info.file_id,
                download_url=info.download_url, raw_path=str(asset.path), retrieved_at=asset.retrieved_at,
                published_at=info.published_at, metadata_json=info.metadata).on_conflict_do_nothing(
                    index_elements=["source_id", "version", "sha256"]))
            release_id = conn.scalar(select(SourceRelease.id).where(SourceRelease.source_id == source_id,
                SourceRelease.version == info.version, SourceRelease.sha256 == asset.sha256))
            states = sorted(frame.get_column("state_code").unique())
            state_ids = {st:stable_jurisdiction_id("state", STATE_FIPS[st], "") for st in states}
            entities = [dict(id=state_ids[st], name=STATE_NAMES[st].title(), level="state", state_code=st) for st in states]
            references, identifiers, relationships = [], [], []
            for row in frame.to_dicts():
                geoid, st = row["geoid"], row["state_code"]
                # A district code can be recycled after redistricting. Scope new
                # identities to this Congress; cross-Congress continuity needs evidence.
                jid = uuid5(JURISDICTION_NS, "congressional_district:119:" + geoid)
                rid = uuid5(REFERENCE_NS, f"{release_id}:congressional_district:{geoid}")
                label = "At-large" if geoid[2:] == "00" else ("Delegate" if st == "DC" else str(int(geoid[2:])))
                name = f"{st} Congressional District {label} (119th Congress)"
                entities.append(dict(id=jid, name=name, level="congressional_district", state_code=st))
                references.append(dict(id=rid, release_id=release_id, jurisdiction_id=jid,
                    kind="congressional_district", geoid=geoid, state_fips=STATE_FIPS[st],
                    name_raw=name, name_key=name.upper(), vintage_start=2024, vintage_end=2024,
                    source_row_number=row["source_row_number"], note="Identifier verified by Census; display name generated; no geometry loaded"))
                identifiers.append(dict(id=uuid5(REFERENCE_NS, f"identifier:{rid}"), jurisdiction_id=jid,
                    reference_id=rid, scheme="CENSUS_CD", value=geoid))
                relationships.append(dict(id=uuid5(REFERENCE_NS, f"relationship:{rid}"),
                    parent_id=state_ids[st], child_id=jid, reference_id=rid, relationship="contains"))
            for chunk in _chunks(entities):
                conn.execute(pg_insert(Jurisdiction).values(chunk).on_conflict_do_nothing(index_elements=["id"]))
            inserted = 0
            for chunk in _chunks(references):
                inserted += len(conn.execute(pg_insert(GeographicReference).values(chunk).on_conflict_do_nothing(
                    index_elements=["release_id", "kind", "geoid"]).returning(GeographicReference.id)).all())
            for model, rows, keys in ((JurisdictionIdentifier, identifiers, ["reference_id", "scheme"]),
                                      (JurisdictionRelationship, relationships, ["reference_id"])):
                for chunk in _chunks(rows):
                    conn.execute(pg_insert(model).values(chunk).on_conflict_do_nothing(index_elements=keys))
            now = datetime.now(timezone.utc)
            conn.execute(update(IngestionRun).where(IngestionRun.id == run_id).values(
                release_id=release_id, status="SUCCEEDED", records_read=validation["records_in_file"],
                records_inserted=inserted, records_updated=0, records_rejected=0,
                warnings_json=[], errors_json=[], raw_sha256=asset.sha256, completed_at=now,
                duration_ms=int((now - (started_at or now)).total_seconds() * 1000)))
        return dict(release_id=str(release_id), records_inserted=inserted,
                    records_already_present=frame.height-inserted, **validation)
