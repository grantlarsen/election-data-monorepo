"""Read-only DATA-002 database inventory, suitable for before/after snapshots.

    python -m app.services.identity_audit --write /app/data/validation/data002_before.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import func, inspect, select, table

from app.database import Base, engine
import app.models  # noqa: F401: load ORM metadata
import app.models.ingestion  # noqa: F401: load source observation metadata


RELEVANT = {
    "person", "person_name", "political_party", "organization", "candidacy",
    "committee_relationship", "external_identifier", "identity_assignment_event",
    "data_source", "source_release", "election_result_observation",
    "geographic_reference", "geographic_resolution", "jurisdiction",
}


def inspect_database(*, all_tables: bool = False) -> dict:
    with engine.connect() as conn:
        i = inspect(conn)
        names = set(i.get_table_names())
        selected = sorted(names if all_tables else names & RELEVANT)
        revision = None
        if "alembic_version" in names:
            # The Alembic version column can be read without reflecting the entire schema.
            from sqlalchemy import text
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        result = {
            "alembic_revisions": revision,
            "database": conn.exec_driver_sql("SELECT current_database()").scalar_one(),
            "tables": {},
            "observation_candidacy_links_need_provenance_review": None,
        }
        for name in selected:
            actual_columns = i.get_columns(name)
            model = Base.metadata.tables.get(name)
            result["tables"][name] = {
                "rows": conn.scalar(select(func.count()).select_from(table(name))),
                "columns": [{"name": col["name"], "type": str(col["type"]),
                             "nullable": col["nullable"]} for col in actual_columns],
                "primary_key": i.get_pk_constraint(name).get("constrained_columns", []),
                "foreign_keys": [{"columns": f["constrained_columns"],
                                  "target_table": f["referred_table"],
                                  "target_columns": f["referred_columns"]}
                                 for f in i.get_foreign_keys(name)],
                "unique_constraints": [{"name": c["name"], "columns": c["column_names"]}
                                       for c in i.get_unique_constraints(name)],
                "indexes": [{"name": idx["name"], "columns": idx["column_names"],
                             "unique": idx["unique"]} for idx in i.get_indexes(name)],
                "model_missing_columns": sorted({c.name for c in model.columns} -
                                                {c["name"] for c in actual_columns}) if model is not None else None,
                "database_unmodeled_columns": sorted({c["name"] for c in actual_columns} -
                                                   {c.name for c in model.columns}) if model is not None else None,
            }
        if "election_result_observation" in names:
            from app.models.ingestion import ElectionResultObservation
            result["observation_candidacy_links_need_provenance_review"] = conn.scalar(
                select(func.count()).select_from(ElectionResultObservation).where(
                    ElectionResultObservation.candidacy_id.is_not(None)))
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only database inventory for DATA-002")
    parser.add_argument("--all-tables", action="store_true", help="include all accessible non-system tables")
    parser.add_argument("--write", type=Path, help="write JSON snapshot to a named file")
    args = parser.parse_args()
    output = json.dumps(inspect_database(all_tables=args.all_tables), indent=2, default=str) + "\n"
    if args.write is not None:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(output, encoding="utf-8")
        print(f"Wrote read-only inventory to {args.write}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
