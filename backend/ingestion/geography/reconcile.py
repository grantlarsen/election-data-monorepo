"""Read-only, seven-election-year reconciliation using the existing resolver."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone


VINTAGES = (2000, 2004, 2012, 2020, 2024)
YEARS = (2000, 2004, 2008, 2012, 2016, 2020, 2024)
MATCHED = frozenset({"RESOLVED", "RESOLVED_HISTORICAL", "RESOLVED_ALIAS"})
CLASSIFIED = MATCHED | {"NON_COUNTY_CLASSIFIED"}


def combine_reports(reports: list[dict], *, expected_observations: int = 94151) -> dict:
    """Pure aggregation; rejects duplicate/missing election years and bad sums."""
    statuses = Counter()
    by_year = Counter()
    transitions = Counter()
    regressions = []
    reassignments = []
    diffs = []
    coverage = []
    votes = []
    preview_digests = []
    seen_years = set()
    for report in reports:
        years = set(report["election_years"])
        if seen_years & years:
            raise ValueError(f"An election year was counted twice: {seen_years & years}")
        seen_years.update(years)
        count = sum(report["status_counts"].values())
        if count != report["records_examined"]:
            raise ValueError("Per-report counts do not reconcile")
        if not report["dry_run"] or report["published"] or not report["vote_totals_unchanged"]:
            raise ValueError("Reconciliation requires read-only previews and unchanged vote totals")
        statuses.update(report["status_counts"])
        coverage.extend(report["coverage_by_year_state"])
        votes.extend(report["vote_totals_by_year_state"])
        for x in report["coverage_by_year_state"]:
            by_year[x["year"]] += x["observations"]
        for x in report["differences"]:
            transitions[(x["old_status"] or "NEW", x["proposed_status"])] += 1
            diffs.append(x)
            if x["old_status"] in MATCHED and x["proposed_status"] not in MATCHED:
                regressions.append(x)
            if (x["old_jurisdiction_id"] is not None and
                    x["proposed_jurisdiction_id"] is not None and
                    x["old_jurisdiction_id"] != x["proposed_jurisdiction_id"]):
                reassignments.append(x)
        preview_digests.append({"reference_vintage": report["vintage"],
                                "release_id": report["reference_release_id"],
                                "proposal_sha256": report.get("proposal_sha256")})
    if seen_years != set(YEARS):
        raise ValueError(f"Election-year coverage incomplete: {sorted(set(YEARS) - seen_years)}")
    total = sum(statuses.values())
    matched = sum(statuses[s] for s in MATCHED)
    classified = sum(statuses[s] for s in CLASSIFIED)
    by_year_status = [dict(x) for x in sorted(coverage, key=lambda x: (x["year"], x["state"], x["status"]))]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "medsl_presidential_county", "reference_vintages": list(VINTAGES),
        "election_years": sorted(seen_years),
        "expected_observations": expected_observations, "total_observations": total,
        "complete": total == expected_observations and set(by_year) == set(YEARS),
        "status_counts": dict(sorted(statuses.items())),
        "county_matched": matched, "county_match_rate": matched / total if total else 0,
        "matched_or_non_county_classified": classified,
        "classification_coverage": classified / total if total else 0,
        "review_required": total - classified,
        "by_election_year": dict(sorted(by_year.items())),
        "coverage_by_year_state": by_year_status,
        "vote_totals_by_year_state": sorted(votes, key=lambda x: (x["year"], x["state"])),
        "vote_totals_unchanged": True,
        "changed_decisions": len(diffs),
        "transition_counts": [
            {"old_status": old, "proposed_status": new, "observations": n}
            for (old, new), n in sorted(transitions.items())
        ],
        "resolved_match_downgrades": len(regressions),
        "resolved_match_downgrade_details": regressions,
        "canonical_reassignments": len(reassignments),
        "canonical_reassignment_details": reassignments,
        "all_decision_changes": diffs,
        "preview_digests": preview_digests,
        "publication_permitted": False,  # always a planning report, never an approval
    }


def reconcile_all(engine, *, expected_observations: int = 94151) -> dict:
    if expected_observations < 1:
        raise ValueError("Expected observation count must be positive")
    from ingestion.geography.resolve import resolve_medsl
    reports = []
    for vintage in VINTAGES:
        report, _ = resolve_medsl(engine, vintage=vintage, dry_run=True, publish=False)
        reports.append(report)
    return combine_reports(reports, expected_observations=expected_observations)
