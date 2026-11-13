"""Run: python -m ingestion run medsl_presidential_county [options]."""
from __future__ import annotations

import argparse
import importlib
import re
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4

from ingestion.source import acquire, atomic_json

LOG = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Versioned election data ingestion")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("source", help="Adapter module name, e.g. medsl_presidential_county")
    run_parser.add_argument("--refresh", action="store_true", help="Re-download official original file")
    run_parser.add_argument("--validate-only", action="store_true", help="Validate only; do not access DB")
    run_parser.add_argument("--dry-run", action="store_true", help="Validate and preview against DB; no DB writes")
    run_parser.add_argument("--years", nargs="+", type=int, default=None, help="Subset of election years")
    run_parser.add_argument("--verbose", action="store_true")
    run_parser.add_argument("--state-totals-csv", type=Path, help="Optional independent state-year totals reference")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.source):
        parser.error("Invalid source adapter name")
    try:
        module = importlib.import_module(f"ingestion.adapters.{args.source}")
        adapter = module.Job()
    except (ImportError, AttributeError) as exc:
        parser.error(f"Unknown or broken source adapter {args.source}: {exc}")
    years = set(args.years) if args.years else set(adapter.supported_years)
    if not years or not years.issubset(adapter.supported_years):
        parser.error(f"--years must be selected from {sorted(adapter.supported_years)}")
    if args.validate_only and args.dry_run:
        parser.error("Use either --validate-only or --dry-run, not both")

    start = monotonic()
    started_at = datetime.now(timezone.utc)
    run_id = uuid4()
    data_dir = Path(os.environ.get("INGESTION_DATA_DIR", "data/ingestion"))
    report_path = data_dir / "reports" / f"{run_id}.json"
    asset = None
    engine = None
    source_id = None
    run_registered = False
    raw_count = 0
    selected_count = 0
    issues: list[dict] = []
    rejections: list[dict] = []
    mode = "validate_only" if args.validate_only else "dry_run" if args.dry_run else "load"
    report: dict = {"run_id": str(run_id), "source": args.source, "mode": mode,
                    "years": sorted(years), "started_at": started_at.isoformat(), "status": "STARTED"}
    try:
        # A normal ingestion records its attempt before touching the network.
        if mode == "load":
            from app.database import engine as app_engine
            from ingestion.loader import register_run
            # Reuse the project's existing DB_USER / DB_PASSWORD / DB_NAME configuration.
            engine = app_engine
            source_id = register_run(engine, run_id, args.source, adapter.source_url,
                                     started_at, {"years":sorted(years), "refresh":args.refresh})
            run_registered = True

        LOG.info("Source: %s; years: %s; mode: %s", args.source, sorted(years), mode)
        asset = acquire(adapter, data_dir, refresh=args.refresh)
        report.update({"dataset_version": asset.info.version, "file_id": asset.info.file_id,
                       "download_url": asset.info.download_url, "raw_path": str(asset.path),
                       "sha256": asset.sha256, "retrieved_at": asset.retrieved_at.isoformat(),
                       "published_at": asset.info.published_at.isoformat() if asset.info.published_at else None})
        raw = adapter.parse(asset.path)
        raw_count = raw.height
        # Only rows for selected elections enter the database. All other raw rows remain cached in source file.
        df = adapter.normalize(raw)
        selected = adapter.select(df, years)
        selected_count = selected.height
        check = adapter.validate(selected, years, args.state_totals_csv)
        issues = check.issues
        rejections = check.rejections
        report.update({"records_in_file": raw_count, "records_selected": selected_count,
                       "records_rejected": len(rejections), "issues": issues})
        if rejections:
            rejections_path = data_dir / "rejections" / f"{run_id}.json"
            atomic_json(rejections_path, {"run_id": str(run_id), "rejections": rejections})
            report["rejections_path"] = str(rejections_path)
        if not check.ok:
            raise ValueError("Validation failed; no election observations were committed")

        if mode == "validate_only":
            report["status"] = "VALIDATED"
        elif mode == "dry_run":
            from app.database import engine as db
            try:
                report["database_preview"] = adapter.preview(db, asset.info.version, asset.sha256, years)
            finally:
                db.dispose()
            report["status"] = "DRY_RUN"
        else:
            assert engine is not None and source_id is not None
            now = datetime.now(timezone.utc)
            stats = adapter.load(engine, source_id, run_id, asset, selected, years, issues,
                                 started_at, now, int((monotonic() - start) * 1000), raw_count)
            report.update({"status": "SUCCEEDED", "records_inserted": stats.inserted,
                           "records_updated": stats.updated, "records_already_present": stats.existing,
                           "active_years_switched": stats.switched_years})
    except Exception as exc:
        LOG.exception("Ingestion failed")
        report["status"] = "FAILED_VALIDATION" if rejections or any(i["severity"] == "ERROR" for i in issues) else "FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        if run_registered and engine is not None:
            from ingestion.loader import finish_failed
            try:
                finish_failed(engine, run_id, status=report["status"],
                              completed_at=datetime.now(timezone.utc), duration_ms=int((monotonic() - start) * 1000),
                              records_read=raw_count,
                              raw_sha256=asset.sha256 if asset else None,
                              warnings=[x for x in issues if x["severity"] == "WARNING"],
                              errors=[x for x in issues if x["severity"] == "ERROR"] + [{"message": str(exc)}],
                              rejections=rejections)
            except Exception as audit_exc:
                LOG.error("Could not persist failure audit: %s", audit_exc)
                report["audit_error"] = str(audit_exc)
    finally:
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["duration_ms"] = int((monotonic() - start) * 1000)
        atomic_json(report_path, report)
        LOG.info("Report: %s (%s)", report_path, report["status"])
        if engine is not None:
            engine.dispose()
    return 0 if report["status"] in {"VALIDATED", "DRY_RUN", "SUCCEEDED"} else 1


if __name__ == "__main__":
    sys.exit(main())
