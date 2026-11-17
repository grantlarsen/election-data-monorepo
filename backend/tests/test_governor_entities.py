from copy import deepcopy

import pytest

from app.services.governor_entities import candidate_key, context_catalog, incumbent_evidence, race_context


def test_source_keys_separate_states_and_parties_and_exclude_buckets():
    candidate = {"name": "Alex Smith", "party": "R"}
    assert candidate_key("GOV-IA", candidate) == candidate_key("GOV-IA", candidate)
    assert candidate_key("GOV-IA", candidate) != candidate_key("GOV-GA", candidate)
    assert candidate_key("GOV-IA", candidate) != candidate_key("GOV-IA", {**candidate, "party": "D"})
    for label in ["Write-in", "Other", "Scattering"]:
        assert candidate_key("GOV-IA", {**candidate, "name": label}) is None


def test_incumbency_matches_reviewed_state_party_and_exact_source_label():
    catalog = context_catalog()
    race = {"id": "GOV-NV", "state_code": "NV"}
    candidate = {"name": "Joe Lombardo", "party": "R"}
    evidence = incumbent_evidence(race, candidate, catalog)
    assert evidence["as_of"] == "2026-11-03" and evidence["source_sha256"]
    assert incumbent_evidence(race, {**candidate, "name": "Aaron Ford", "party": "D"}, catalog) is None
    assert incumbent_evidence(race, {**candidate, "party": "D"}, catalog) is None
    assert incumbent_evidence({**race, "id": "GOV-GA"}, candidate, catalog) is None
    assert incumbent_evidence({"id": "GOV-SD", "state_code": "SD"}, {"name": "Larry Rhoden", "party": "R"}, catalog)
    assert incumbent_evidence({"id": "GOV-MN", "state_code": "MN"}, {"name": "Amy Klobuchar", "party": "D"}, catalog) is None


@pytest.mark.parametrize("state,year,party", [("NV", 2022, "R"), ("AZ", 2022, "D"), ("NH", 2024, "R"), ("VT", 2024, "R")])
def test_previous_election_is_state_specific(state, year, party):
    assert context_catalog()["previous_elections"][state]["year"] == year
    assert context_catalog()["previous_elections"][state]["party"] == party


@pytest.mark.parametrize("status,outcome,party,expected", [
    ("counting", "leads", "D", None), ("called", "won", "D", True), ("final", "won", "D", True),
    ("called", "won", "R", False), ("called", "", "D", None), ("called", "won", "", None),
])
def test_flip_requires_a_unique_call_not_a_lead(status, outcome, party, expected):
    race = {"state_code": "NV", "status": status, "candidates": [{"party": party, "outcome": outcome}]}
    context = race_context(race, context_catalog())
    assert context["flipped"] is expected
    assert context["previous_election"]["year"] == 2022
    assert context["previous_election"]["source_url"].startswith("https://www.nga.org/")
    if outcome == "won":
        ambiguous = deepcopy(race)
        ambiguous["candidates"].append({"party": "D", "outcome": "won"})
        assert race_context(ambiguous, context_catalog())["flipped"] is None
