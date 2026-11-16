"""Preview or publish source-traceable 2024 House returns."""
import argparse
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.services.house_returns import publish
from ingestion.source import atomic_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--reference-release-id", type=UUID)
    parser.add_argument("--output", type=Path, default=Path("data/house-returns/publication.json"))
    args = parser.parse_args(argv)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            report = publish(session, dry_run=not args.publish, allow_partial=args.allow_partial,
                             reference_release_id=args.reference_release_id)
        atomic_json(args.output, report)
        print(f"{report['action']}: {report['accepted_rows']} accepted, {report['excluded_rows']} excluded; {args.output}")
        return 0
    except ValueError as exc:
        parser.exit(1, f"House publication failed: {exc}\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
