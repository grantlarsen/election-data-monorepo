"""Pure tests for the publish gate, including concurrent-review drift."""
from uuid import uuid4

import pytest
from ingestion.geography.publication import proposal_fingerprint, high_risk_changes, enforce_approval


def diff(old="RESOLVED", new="AMBIGUOUS", original="X", proposed=None):
    return {"observation_id": str(uuid4()), "old_status": old, "proposed_status": new,
            "old_jurisdiction_id": original, "proposed_jurisdiction_id": proposed}


def test_digest_reproducible_and_release_scoped():
    release = uuid4()
    item = diff()
    a = proposal_fingerprint(release, "step6.2.0", [item])
    assert a == proposal_fingerprint(release, "step6.2.0", [item])
    assert a != proposal_fingerprint(uuid4(), "step6.2.0", [item])
    assert a != proposal_fingerprint(release, "step6.2.1", [item])
    assert a != proposal_fingerprint(release, "step6.2.0", [])


def test_requires_review_digest_and_separate_downgrade_flag():
    d = diff()
    downs, changes = high_risk_changes([d])
    assert len(downs) == 1 and len(changes) == 0
    args = dict(revised=1, actor="qa", approve_changes=True,
                preview_digest="abc", current_digest="abc",
                downgrade_count=1, reassignment_count=0,
                allow_downgrades=False, allow_jurisdiction_reassignment=False)
    with pytest.raises(ValueError, match="allow-downgrades"):
        enforce_approval(**args)
    with pytest.raises(ValueError, match="expected-proposal-sha256"):
        enforce_approval(**{**args, "preview_digest": "outdated"})
    with pytest.raises(ValueError, match="approve-changes"):
        enforce_approval(**{**args, "approve_changes": False})
    with pytest.raises(ValueError, match="approve-changes"):
        enforce_approval(**{**args, "actor": None})
    enforce_approval(**{**args, "allow_downgrades": True})


def test_canonical_reassignment_needs_separate_flag():
    d = diff(old="RESOLVED", new="RESOLVED", original="county_1", proposed="county_2")
    downs, changes = high_risk_changes([d]); assert not downs and len(changes) == 1
    args = dict(revised=1, actor="qa", approve_changes=True,
                preview_digest="abc", current_digest="abc",
                downgrade_count=0, reassignment_count=1,
                allow_downgrades=False, allow_jurisdiction_reassignment=False)
    with pytest.raises(ValueError, match="allow-jurisdiction-reassignment"):
        enforce_approval(**args)
    enforce_approval(**{**args, "allow_jurisdiction_reassignment": True})
