"""Run with `python -m ingestion.canonical_cli medsl --year 2008 [--publish --allow-partial]`."""
from __future__ import annotations

import argparse
import json
from uuid import UUID


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="DATA-003 conservative canonical materialization")
    p.add_argument("source", choices=["medsl"])
    p.add_argument("--year", required=True, type=int)
    p.add_argument("--reference-release-id", type=UUID)
    p.add_argument("--publish", action="store_true", help="Commit the selected source-backed subset")
    p.add_argument("--allow-partial", action="store_true", help="Acknowledge explicit exclusions in publication")
    args = p.parse_args(argv)
    from app.database import SessionLocal
    from app.services.canonical_results import materialize_medsl_year
    with SessionLocal() as session, session.begin():
        session.execute(__import__("sqlalchemy").text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        report = materialize_medsl_year(session, year=args.year, dry_run=not args.publish,
            allow_partial=args.allow_partial, reference_release_id=args.reference_release_id)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
