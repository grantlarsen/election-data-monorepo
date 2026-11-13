"""Same ingestion CLI, new Census adapter and geographic review subcommands."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from ingestion.source import acquire, atomic_json

LOG = logging.getLogger(__name__)


def run_geographic_job(adapter, args) -> int:
    from ingestion.loader import finish_failed, register_run

    if args.vintage not in adapter.supported_vintages:
        raise ValueError(f"--vintage must be one of {sorted(adapter.supported_vintages)}")
    if args.years or args.state_totals_csv:
        raise ValueError("Geographic ingestion uses --vintage, not MEDSL --years or --state-totals-csv")
    if args.validate_only and args.dry_run:
        raise ValueError("Use either --validate-only or --dry-run")
    mode = "validate_only" if args.validate_only else "dry_run" if args.dry_run else "load"
    data_dir = Path(os.getenv("INGESTION_DATA_DIR", "data/ingestion"))
    started = datetime.now(timezone.utc)
    run_id = uuid4()
    report_path = data_dir / "reports" / f"{run_id}.json"
    report = {"run_id": str(run_id), "source": adapter.key, "mode": mode,
              "vintage": args.vintage, "status": "STARTED", "started_at": started.isoformat()}
    registered = False
    engine = None
    asset = None
    raw_count = 0
    begin = monotonic()
    try:
        if mode == "load":
            from app.database import engine as app_engine
            engine = app_engine
            source_id = register_run(engine, run_id, adapter.key, adapter.source_url, started,
                                     {"vintage": args.vintage, "refresh": args.refresh})
            registered = True
        asset = acquire(adapter, data_dir, refresh=args.refresh)
        raw = adapter.parse(asset.path)
        raw_count = raw.height
        validation = adapter.validate(raw)
        report.update({"source_release_version": asset.info.version,
                       "source_url": asset.info.download_url,
                       "sha256": asset.sha256, "raw_path": str(asset.path),
                       "source_metadata": asset.info.metadata,
                       "validation": validation})
        if mode == "validate_only":
            report["status"] = "VALIDATED"
        elif mode == "dry_run":
            report["status"] = "DRY_RUN"
        else:
            report.update(adapter.load(engine, source_id, run_id, asset, raw, validation, started_at=started))
            report["status"] = "SUCCEEDED"
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        LOG.exception("Geographic ingestion failed")
        if registered and engine:
            try:
                finish_failed(engine, run_id, status="FAILED",
                              completed_at=datetime.now(timezone.utc),
                              duration_ms=int((monotonic() - begin) * 1000),
                              records_read=raw_count,
                              raw_sha256=asset.sha256 if asset else None,
                              warnings=[], errors=[{"message": str(exc)}], rejections=[])
            except Exception as audit_exc:
                report["audit_error"] = str(audit_exc)
    finally:
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["duration_ms"] = int((monotonic() - begin) * 1000)
        atomic_json(report_path, report)
        LOG.info("Geographic report: %s (%s)", report_path, report["status"])
        if engine is not None:
            engine.dispose()
    return 0 if report["status"] in {"SUCCEEDED", "VALIDATED", "DRY_RUN"} else 1


def geo_command(args) -> int:
    from app.database import engine
    from ingestion.geography.resolve import choose_release, resolve_medsl
    from ingestion.geography.quality import (active_medsl_anomalies, save_csv,
                                             unresolved_rows, validate_loaded_reference, reference_changes)
    data_dir = Path(os.getenv("INGESTION_DATA_DIR", "data/ingestion"))
    run_id = uuid4()
    try:
        if args.operation == "changes":
            changes = reference_changes(engine)
            report_path = data_dir / "geography" / f"reference-changes-{run_id}.json"
            atomic_json(report_path, changes)
            print({k:v for k,v in changes.items() if k != "changes"})
            print(f"Full cross-vintage evidence: {report_path}")
            return 0
        if args.operation == "anomalies":
            detail = active_medsl_anomalies(engine)
            out = Path(args.output) if args.output else data_dir / "geography" / f"medsl-anomalies-{run_id}.csv"
            save_csv(out, detail.pop("detail"))
            detail["all_affected_rows_csv"] = str(out)
            print(detail)
            return 0
        if args.vintage is None:
            raise ValueError(f"geo {args.operation} requires --vintage")
        with engine.connect() as conn:
            release_id, _, _ = choose_release(conn, args.vintage,
                                               UUID(args.release_id) if args.release_id else None,
                                               source_name=args.source)
        if args.operation == "validate":
            detail = validate_loaded_reference(engine, release_id)
            out = data_dir / "geography" / f"validate-{run_id}.json"
            atomic_json(out, detail)
            print(f"{detail} — report {out}")
            return 0 if detail["ok"] else 1
        if args.operation == "resolve":
            detail, review = resolve_medsl(engine, vintage=args.vintage, years=args.years,
                                           release_id=release_id, dry_run=args.dry_run,
                                           source_name=args.source)
            out = Path(args.output) if args.output else data_dir / "geography" / f"review-{run_id}.csv"
            save_csv(out, review)
            detail["review_csv"] = str(out)
            report_path = data_dir / "geography" / f"resolution-{run_id}.json"
            atomic_json(report_path, detail)
            print({k: v for k, v in detail.items() if k != "coverage_by_year_state"})
            print(f"Coverage by year/state: {report_path}")
            return 0
        if args.operation == "unresolved":
            review = unresolved_rows(engine, release_id)
            out = Path(args.output) if args.output else data_dir / "geography" / f"unresolved-{run_id}.csv"
            save_csv(out, review)
            print(f"{len(review)} unresolved or ambiguous decisions exported to {out}")
            return 0
        raise ValueError(f"Unknown geographic operation: {args.operation}")
    except (ValueError, RuntimeError) as exc:
        LOG.error("Geographic operation failed: %s", exc)
        print(f"ERROR: {exc}")
        return 1
    finally:
        engine.dispose()
