"""Preview or publish source-traceable statewide Senate returns."""
import argparse
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.services.senate_returns import publish
from ingestion.senate_returns import YEARS
from ingestion.source import atomic_json

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, choices=sorted(YEARS), default=sorted(YEARS))
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--reference-release-id", type=UUID)
    parser.add_argument("--output", type=Path, default=Path("data/senate-returns/publication.json"))
    args = parser.parse_args(argv)
    try:
        # All selected years and pointer changes commit atomically.
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            reports = [publish(session, year=year, dry_run=not args.publish, allow_partial=args.allow_partial,
                               reference_release_id=args.reference_release_id) for year in sorted(set(args.years))]
        atomic_json(args.output, dict(years=reports))
        for report in reports:
            logger.info("Senate publication", extra={k: report[k] for k in
                        ("year", "action", "accepted_rows", "excluded_rows", "fingerprint")})
            print(f"{report['year']} {report['action']}: {report['accepted_rows']} accepted, {report['excluded_rows']} excluded")
        return 0
    except ValueError as exc:
        parser.exit(1, f"Senate publication failed: {exc}\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
