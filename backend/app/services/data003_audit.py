"""DATA-003 read-only inventory and MEDSL canonicalization preflight.

Run inside the API container (which has DB_* from Compose):
    python -m app.services.data003_audit

Emits JSON on stdout. Never changes schema or data. Summaries use currently
active source releases but DO NOT imply that their rows are canonical results.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from sqlalchemy import text

from app.database import engine
from app.services.identity_audit import inspect_database


# Every query is read-only, and is executed in a read-only transaction.
QUERIES = {
    "release_inventory": """
        SELECT s.name AS source, r.id AS release_id, r.version, r.sha256,
               r.retrieved_at, count(o.id) AS observation_rows,
               count(DISTINCT o.year) AS observation_years
        FROM source_release r
        JOIN data_source s ON s.id = r.source_id
        LEFT JOIN election_result_observation o ON o.release_id = r.id
        GROUP BY s.name, r.id, r.version, r.sha256, r.retrieved_at
        ORDER BY s.name, r.version, r.sha256
    """,
    "active_source_years": """
        SELECT s.name AS source, a.year, a.release_id,
               r.version, r.sha256, a.applied_at,
               count(o.id) AS active_observation_rows
        FROM source_active_year a
        JOIN data_source s ON s.id = a.source_id
        JOIN source_release r ON r.id = a.release_id
        LEFT JOIN election_result_observation o ON
           o.release_id = a.release_id AND o.year = a.year
        GROUP BY s.name, a.year, a.release_id, r.version, r.sha256, a.applied_at
        ORDER BY s.name, a.year
    """,
    "active_observation_years": """
        SELECT o.year, count(*) AS observations,
               count(*) FILTER (WHERE o.candidate_votes IS NULL) AS missing_candidate_votes,
               count(*) FILTER (WHERE o.total_votes IS NULL) AS missing_reported_total,
               count(*) FILTER (WHERE o.jurisdiction_id IS NOT NULL) AS direct_jurisdiction_links,
               count(*) FILTER (WHERE o.candidacy_id IS NOT NULL) AS direct_candidacy_links,
               count(*) FILTER (WHERE o.party_id IS NOT NULL) AS direct_party_links,
               sum(o.candidate_votes) AS raw_candidate_votes_sum_not_reconciled
        FROM election_result_observation o
        JOIN source_release r ON r.id = o.release_id
        JOIN source_active_year a ON a.release_id = o.release_id
             AND a.source_id = r.source_id AND a.year = o.year
        GROUP BY o.year ORDER BY o.year
    """,
    "active_observation_candidate_kind": """
        SELECT o.year, o.candidate_kind, count(*) AS observations,
               count(*) FILTER (WHERE o.candidate_votes IS NULL) AS votes_missing
        FROM election_result_observation o
        JOIN source_release r ON r.id = o.release_id
        JOIN source_active_year a ON a.release_id = o.release_id
             AND a.source_id = r.source_id AND a.year = o.year
        GROUP BY o.year, o.candidate_kind ORDER BY o.year, o.candidate_kind
    """,
    "active_observation_offices_modes": """
        SELECT o.year, o.office_raw, o.mode_normalized,
               count(*) AS observations,
               count(DISTINCT o.state_code) AS states
        FROM election_result_observation o
        JOIN source_release r ON r.id = o.release_id
        JOIN source_active_year a ON a.release_id = o.release_id
             AND a.source_id = r.source_id AND a.year = o.year
        GROUP BY o.year, o.office_raw, o.mode_normalized
        ORDER BY o.year, o.office_raw, o.mode_normalized
    """,
    "current_geo_resolution_by_reference_release": """
        SELECT o.year, g.reference_release_id, rr.version AS reference_version,
               g.status, count(*) AS observations,
               count(*) FILTER (WHERE g.jurisdiction_id IS NOT NULL) AS jurisdiction_links,
               count(*) FILTER (WHERE g.reference_id IS NOT NULL) AS reference_links
        FROM geographic_resolution g
        JOIN election_result_observation o ON o.id = g.observation_id
        JOIN source_release r ON r.id = o.release_id
        JOIN source_active_year a ON a.release_id = o.release_id
              AND a.source_id = r.source_id AND a.year = o.year
        JOIN source_release rr ON rr.id = g.reference_release_id
        WHERE NOT EXISTS (
              SELECT 1 FROM geographic_resolution child WHERE child.supersedes_id = g.id)
        GROUP BY o.year, g.reference_release_id, rr.version, g.status
        ORDER BY o.year, g.reference_release_id, g.status
    """,
    "ambiguous_geo_resolution_chains": """
        WITH leaf AS (
             SELECT g.observation_id, g.reference_release_id
             FROM geographic_resolution g
             WHERE NOT EXISTS (
                 SELECT 1 FROM geographic_resolution child WHERE child.supersedes_id = g.id)
        ), duplicates AS (
             SELECT observation_id, reference_release_id, count(*) AS leaves
             FROM leaf GROUP BY observation_id, reference_release_id
             HAVING count(*) > 1
        )
        SELECT count(*) AS duplicated_observation_reference_pairs,
               coalesce(sum(leaves), 0) AS affected_leaves
        FROM duplicates
    """,
    "geo_resolution_reference_link_mismatch": """
        SELECT count(*) AS mismatched_reference_jurisdiction_links
        FROM geographic_resolution g
        JOIN geographic_reference ref ON ref.id = g.reference_id
        WHERE NOT EXISTS (
           SELECT 1 FROM geographic_resolution child WHERE child.supersedes_id = g.id)
          AND (ref.jurisdiction_id IS DISTINCT FROM g.jurisdiction_id
               OR ref.release_id IS DISTINCT FROM g.reference_release_id)
    """,
    "active_duplicate_logical_keys": """
        WITH d AS (
          SELECT o.release_id, o.logical_key, count(*) AS n
          FROM election_result_observation o
          JOIN source_release r ON r.id = o.release_id
          JOIN source_active_year a ON a.release_id = o.release_id
                  AND a.source_id = r.source_id AND a.year = o.year
          GROUP BY o.release_id, o.logical_key HAVING count(*) > 1
        )
        SELECT count(*) AS duplicated_keys, coalesce(sum(n),0) AS affected_observations
        FROM d
    """,
    "active_conflicting_reported_totals": """
        WITH d AS (
          SELECT o.release_id, o.year, o.state_code,
                 o.county_fips, o.county_raw, o.mode_normalized,
                 count(DISTINCT o.total_votes) AS distinct_reported_totals
          FROM election_result_observation o
          JOIN source_release r ON r.id = o.release_id
          JOIN source_active_year a ON a.release_id = o.release_id
                  AND a.source_id = r.source_id AND a.year = o.year
          WHERE o.total_votes IS NOT NULL
          GROUP BY o.release_id, o.year, o.state_code, o.county_fips,
                   o.county_raw, o.mode_normalized
          HAVING count(DISTINCT o.total_votes) > 1
        )
        SELECT count(*) AS conflicting_geography_year_mode_groups FROM d
    """,
    "multiple_party_labels_example": """
        SELECT o.year, o.state_code, o.candidate_normalized,
               count(DISTINCT o.party_normalized) AS distinct_parties,
               array_agg(DISTINCT o.party_normalized) AS party_labels
        FROM election_result_observation o
        JOIN source_release r ON r.id = o.release_id
        JOIN source_active_year a ON a.release_id = o.release_id
               AND a.source_id = r.source_id AND a.year = o.year
        WHERE o.candidate_kind = 'candidate'
          AND o.candidate_normalized IS NOT NULL
        GROUP BY o.year, o.state_code, o.candidate_normalized
        HAVING count(DISTINCT o.party_normalized) > 1
        ORDER BY o.year, o.state_code, o.candidate_normalized
        LIMIT 30
    """,
    "active_geo_resolution_rows": """
        SELECT count(*) AS active_observations_with_any_resolution,
               count(*) FILTER (WHERE n > 1) AS observations_with_multiple_reference_vintages
        FROM (
          SELECT g.observation_id, count(DISTINCT g.reference_release_id) AS n
          FROM geographic_resolution g
          JOIN election_result_observation o ON o.id = g.observation_id
          JOIN source_release r ON r.id = o.release_id
          JOIN source_active_year a ON a.release_id = o.release_id
                 AND a.source_id = r.source_id AND a.year = o.year
          WHERE NOT EXISTS (SELECT 1 FROM geographic_resolution child
                            WHERE child.supersedes_id = g.id)
          GROUP BY g.observation_id
        ) d
    """,
}


def audit() -> dict:
    # Existing inspector covers columns, model-vs-live column differences,
    # PKs, FKs, unique constraints, indexes and exact row counts.
    inventory = inspect_database(all_tables=True)
    tables = set(inventory["tables"])
    required = {
        "release_inventory": {"source_release", "data_source", "election_result_observation"},
        "active_source_years": {"source_active_year", "source_release", "data_source", "election_result_observation"},
        "active_observation_years": {"source_active_year", "source_release", "election_result_observation"},
        "active_observation_candidate_kind": {"source_active_year", "source_release", "election_result_observation"},
        "active_observation_offices_modes": {"source_active_year", "source_release", "election_result_observation"},
        "current_geo_resolution_by_reference_release": {"geographic_resolution", "election_result_observation", "source_release", "source_active_year"},
        "ambiguous_geo_resolution_chains": {"geographic_resolution"},
        "geo_resolution_reference_link_mismatch": {"geographic_resolution", "geographic_reference"},
        "active_duplicate_logical_keys": {"election_result_observation", "source_active_year", "source_release"},
        "active_conflicting_reported_totals": {"election_result_observation", "source_active_year", "source_release"},
        "multiple_party_labels_example": {"election_result_observation", "source_active_year", "source_release"},
        "active_geo_resolution_rows": {"geographic_resolution", "election_result_observation", "source_release", "source_active_year"},
    }
    evidence = {}
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        for name, sql in QUERIES.items():
            missing = sorted(required[name] - tables)
            if missing:
                evidence[name] = {"blocked_missing_tables": missing}
                continue
            evidence[name] = [dict(row) for row in conn.execute(text(sql)).mappings()]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "note": "No observations materialized; votes in this report are RAW, not canonical.",
        "inventory": inventory,
        "evidence": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only DATA-003 database audit")
    parser.parse_args()
    print(json.dumps(audit(), indent=2, default=str))


if __name__ == "__main__":
    main()
