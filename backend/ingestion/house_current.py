"""Refresh or replay source-traceable provisional 2026 House results."""
import argparse
import json
from pathlib import Path

from app.services.house_results import read_snapshot, refresh_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--force", action="store_true", help="Check upstream before the 24-hour cache expires")
    parser.add_argument('--cache-only', action='store_true', help='Refresh counts without registering source profiles')
    parser.add_argument("--verify-only", action="store_true", help="Validate archives offline; no network or writes")
    args = parser.parse_args()
    if args.verify_only:
        data = read_snapshot(args.cache_dir)
        report = {key: data[key] for key in ("sha256", "accepted_rows", "excluded_rows", "missing_districts", "checked_at")}
    else:
        report = refresh_snapshot(args.cache_dir, force=args.force)
        if not args.cache_only:
            from app.services.house_entities import sync_cached_entities
            report['profiles'] = sync_cached_entities(args.cache_dir)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
