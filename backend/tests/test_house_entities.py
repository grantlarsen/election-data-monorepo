from app.services.house_entities import candidate_key, incumbent_catalog, incumbent_evidence


def test_house_source_keys_keep_districts_parties_and_anonymous_categories_separate():
    candidate = {'name': 'Alex Smith', 'party': 'R'}
    assert candidate_key('IA-03', candidate) == candidate_key('IA-03', candidate)
    assert candidate_key('IA-03', candidate) != candidate_key('IA-04', candidate)
    assert candidate_key('IA-03', candidate) != candidate_key('IA-03', {**candidate, 'party': 'D'})
    for label in ['Write-in', 'Other', 'Scattering']:
        assert candidate_key('IA-03', {**candidate, 'name': label}) is None


def test_incumbency_requires_reviewed_race_state_party_and_label_not_a_similar_surname():
    catalog = incumbent_catalog()
    race = {'id': 'IA-03', 'state_code': 'IA'}
    candidate = {'name': 'Zach Nunn', 'party': 'R'}
    evidence = incumbent_evidence(race, candidate, catalog)
    assert evidence['bioguide'] == 'N000193' and evidence['as_of'] == '2026-11-03'
    assert incumbent_evidence(race, {**candidate, 'party': 'D'}, catalog) is None
    assert incumbent_evidence({**race, 'id': 'IA-04'}, candidate, catalog) is None
    assert incumbent_evidence({'id': 'TX-22', 'state_code': 'TX'}, {'name': 'Trever Nehls', 'party': 'R'}, catalog) is None
    assert incumbent_evidence({'id': 'IL-04', 'state_code': 'IL'}, {'name': 'Patty Garcia', 'party': 'D'}, catalog) is None
