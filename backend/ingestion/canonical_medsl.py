"""Conservative MEDSL presidential observation eligibility rules, without DB access.

MEDSL's `party` field is not sufficient evidence for a ballot-line breakdown.
Only TOTAL-mode rows are currently additive and eligible for canonical
publication. Other modes are retained as immutable observations with issues.
"""
from __future__ import annotations

from hashlib import sha256
import json

SUPPORTED_YEARS = frozenset({2000, 2004, 2008, 2012, 2016, 2020, 2024})
DATES = {2000: (11, 7), 2004: (11, 2), 2008: (11, 4), 2012: (11, 6),
         2016: (11, 8), 2020: (11, 3), 2024: (11, 5)}
MATCHED = frozenset({"RESOLVED", "RESOLVED_HISTORICAL", "RESOLVED_ALIAS"})
RULESET = "data003-medsl-1.0.0"


def vote_kind(candidate_kind: str) -> str:
    if candidate_kind == "aggregate":
        return "aggregate"
    if candidate_kind == "write_in":
        return "write_in"
    return "candidate_total"


def eligibility(*, candidate_kind: str, mode: str | None, votes: int | None,
                geo_status: str | None, geo_level: str | None,
                duplicate_key: bool, conflicting_scope: bool,
                conflicting_total: bool = False) -> str | None:
    """Return the first exclusion code, otherwise None.

    A valid geographic status alone is insufficient if its reference is not a
    county or if it is not resolved to a jurisdiction. Caller validates FKs.
    """
    if duplicate_key:
        return "DUPLICATE_LOGICAL_KEY"
    if geo_status not in MATCHED:
        return "GEOGRAPHY_NOT_RESOLVED"
    if geo_level != "county":
        return "UNSUPPORTED_REPORTING_LEVEL"
    if mode != "TOTAL":
        return "UNSUPPORTED_VOTING_MODE"
    if votes is None:
        return "MISSING_VOTES"
    if votes < 0:
        return "INVALID_VOTES"
    if candidate_kind not in {"candidate", "aggregate", "write_in"}:
        return "UNSUPPORTED_CANDIDATE_KIND"
    if conflicting_total:
        return "CONFLICTING_REPORTED_TOTAL"
    if conflicting_scope:
        return "DUPLICATE_CANONICAL_SCOPE"
    return None


def scoped_key(prefix: str, *parts: object) -> str:
    data = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return prefix + ":" + sha256(data.encode("utf-8")).hexdigest()


def unit_reconciliation_issue(rows, excluded_ids: set) -> str | None:
    """Validate complete additive TOTAL-mode source unit (never sum totalvotes)."""
    if any(row.id in excluded_ids for row in rows):
        return 'REPORTING_UNIT_INCOMPLETE'
    totals = {row.total_votes for row in rows if row.total_votes is not None}
    if len(totals) != 1 or any(row.total_votes is None for row in rows):
        return 'MISSING_OR_CONFLICTING_TOTAL'
    if sum(row.candidate_votes or 0 for row in rows) != next(iter(totals)):
        return 'REPORTED_TOTAL_MISMATCH'
    return None
