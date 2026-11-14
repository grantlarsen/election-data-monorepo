"""Pure preview fingerprint and publish gate for immutable resolution decisions."""
from __future__ import annotations

from hashlib import sha256
import json

MATCHED = frozenset({"RESOLVED", "RESOLVED_HISTORICAL", "RESOLVED_ALIAS"})


def proposal_fingerprint(reference_release_id, ruleset_version: str, differences: list[dict]) -> str:
    """Bind an approval to exactly one release, ruleset, and decision diff."""
    payload = {"reference_release_id": str(reference_release_id),
               "ruleset_version": ruleset_version, "differences": differences}
    return sha256(json.dumps(payload, sort_keys=True, default=str,
                             separators=(",", ":")).encode()).hexdigest()


def high_risk_changes(differences: list[dict]) -> tuple[list[dict], list[dict]]:
    downgrades = [x for x in differences
                  if x["old_status"] in MATCHED and x["proposed_status"] not in MATCHED]
    reassigned = [x for x in differences
                  if x["old_jurisdiction_id"] is not None
                  and x["proposed_jurisdiction_id"] is not None
                  and x["old_jurisdiction_id"] != x["proposed_jurisdiction_id"]]
    return downgrades, reassigned


def enforce_approval(*, revised: int, actor: str | None, approve_changes: bool,
                     preview_digest: str | None, current_digest: str,
                     downgrade_count: int, reassignment_count: int,
                     allow_downgrades: bool, allow_jurisdiction_reassignment: bool) -> None:
    """Never trust --approve-changes without an exact preview and separate risk flags."""
    if not revised:
        return
    if not approve_changes or not actor or not actor.strip():
        raise ValueError(f"{revised} resolutions would change; pass --approve-changes --actor")
    if preview_digest != current_digest:
        raise ValueError("Preview/publish decision digest differs or --expected-proposal-sha256 is absent; rerun geo compare")
    if downgrade_count and not allow_downgrades:
        raise ValueError(f"{downgrade_count} resolved matches would be downgraded; explicit --allow-downgrades required")
    if reassignment_count and not allow_jurisdiction_reassignment:
        raise ValueError(f"{reassignment_count} canonical UUIDs would change; explicit --allow-jurisdiction-reassignment required")
