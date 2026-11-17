"""Source-scoped candidate keys and evidence-backed incumbency, without database access."""
import pytest

from app.services.senate_entities import candidate_key, incumbent_evidence


def test_source_candidate_keys_do_not_merge_states_parties_or_anonymous_buckets():
    candidate = {"name": "Alex Smith", "party": "D"}
    assert candidate_key("SEN-FL", candidate) == candidate_key("SEN-FL", candidate)
    assert candidate_key("SEN-FL", candidate) != candidate_key("SEN-OH", candidate)
    assert candidate_key("SEN-FL", candidate) != candidate_key("SEN-FL", {**candidate, "party": "R"})
    assert all(candidate_key("SEN-FL", {"name": name, "party": "O"}) is None
               for name in ["Write-in", "Write-In", "Write-ins", "Other"])


def test_incumbency_requires_reviewed_name_party_state_and_class():
    race = {"state_code": "AK", "seat_class": 2}
    candidate = {"name": "Dan Sullivan", "party": "R"}
    evidence = incumbent_evidence(race, candidate)
    assert evidence["as_of"] == "2026-11-03" and evidence["url"].startswith("https://www.senate.gov/")
    assert incumbent_evidence(race, {**candidate, "party": "D"}) is None
    assert incumbent_evidence({**race, "seat_class": 3}, candidate) is None
    assert incumbent_evidence({**race, "state_code": "OH"}, candidate) is None
    assert incumbent_evidence(race, {"name": "Mary Peltola", "party": "D"}) is None
    assert incumbent_evidence({"state_code": "FL", "seat_class": 3}, {"name": "Ashley Moody", "party": "R"})
    with pytest.raises(ValueError, match="does not cover"):
        incumbent_evidence(race, candidate, catalog={"year": 2028, "as_of": "2028-11-07"})
