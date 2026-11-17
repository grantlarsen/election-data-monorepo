"""Reviewed media scoping, validation, cache replay and attribution."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.services import candidate_media
from ingestion.candidate_portraits import cache_portraits, read_catalog, read_catalogs, validate_image


@pytest.fixture
def catalog(tmp_path):
    content = b"\xff\xd8\xffreviewed-test-photo"
    digest = sha256(content).hexdigest()
    media = {"url": f"/media/candidates/{digest}.jpg", "sha256": digest, "mime_type": "image/jpeg",
             "source": "https://commons.wikimedia.org/wiki/File:Example.jpg", "credit": "Example photographer",
             "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
             "original_url": "https://upload.wikimedia.org/example.jpg",
             "download_url": "https://upload.wikimedia.org/example.jpg", "retrieved_at": "2026-11-17T12:00:00Z"}
    row = {"source": "call_the_map_senate", "year": 2026, "race_id": "SEN-FL", "state_code": "FL",
           "name": "Example candidate", "party": "R", "match_evidence": {"method": "Reviewed political biography"}, "portrait": media}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"schema_version": 1, "candidates": [row]}))
    return path, content, row


def test_media_is_scoped_to_source_election_race_party_and_exact_label(catalog, monkeypatch):
    path, _, row = catalog
    key = (row["source"], row["year"], row["race_id"], row["name"], row["party"])
    monkeypatch.setattr(candidate_media, "portrait_catalog", lambda: {key: row["portrait"]})
    media = candidate_media.candidate_portrait(*key)
    assert media["credit"] == "Example photographer"
    for index, value in enumerate(["another_source", 2028, "SEN-OH", "EXAMPLE CANDIDATE", "D"]):
        changed = list(key)
        changed[index] = value
        assert candidate_media.candidate_portrait(*changed) is None
    media["credit"] = "changed client copy"
    assert candidate_media.candidate_portrait(*key)["credit"] == row["portrait"]["credit"]


@pytest.mark.parametrize("change", ["duplicate", "unsafe_path", "missing_credit", "missing_license", "unsafe_url", "wrong_state", "naive_date"])
def test_rejects_invalid_media_catalogs(catalog, change):
    path, _, row = catalog
    data = read_catalog(path)
    if change == "duplicate":
        data["candidates"].append(deepcopy(row))
    elif change == "unsafe_path":
        data["candidates"][0]["portrait"]["url"] = "/media/candidates/../../outside.jpg"
    elif change == "missing_credit":
        data["candidates"][0]["portrait"]["credit"] = ""
    elif change == "missing_license":
        data["candidates"][0]["portrait"]["license"] = ""
    elif change == "unsafe_url":
        data["candidates"][0]["portrait"]["download_url"] = "https://localhost/private.jpg"
    elif change == "wrong_state":
        data["candidates"][0]["state_code"] = "OH"
    else:
        data["candidates"][0]["portrait"]["retrieved_at"] = "2026-11-17"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_catalog(path)


def test_cache_replay_idempotency_corruption_and_offline_verification(catalog, tmp_path):
    path, content, row = catalog
    data = read_catalog(path)
    calls = []

    def fetch(url):
        calls.append(url)
        return content

    destination = tmp_path / "portraits"
    first = cache_portraits(data, destination, fetch=fetch)
    assert first["inserted"] == 1 and first["rejected"] == 0
    second = cache_portraits(data, destination, fetch=fetch)
    assert second["unchanged"] == 1 and len(calls) == 1
    asset = next(destination.iterdir())
    asset.write_bytes(b"corrupt cache")
    failed = cache_portraits(data, destination, verify_only=True, fetch=fetch)
    assert failed["rejected"] == 1 and len(calls) == 1
    fixed = cache_portraits(data, destination, fetch=fetch)
    assert fixed["updated"] == 1 and len(calls) == 2
    verified = cache_portraits(data, destination, verify_only=True, fetch=fetch)
    assert verified["unchanged"] == 1 and len(calls) == 2


def test_bad_download_does_not_replace_a_cached_file(catalog, tmp_path):
    path, content, row = catalog
    destination = tmp_path / "photos"
    destination.mkdir()
    asset = destination / row["portrait"]["url"].rsplit("/", 1)[-1]
    asset.write_bytes(b"old corrupt bytes retained for investigation")
    result = cache_portraits(read_catalog(path), destination, fetch=lambda _: b"<html>Error</html>")
    assert result["rejected"] == 1 and result["inserted"] == 0 and result["updated"] == 0
    assert asset.read_bytes() == b"old corrupt bytes retained for investigation"
    assert not list(destination.glob("*.tmp"))
    with pytest.raises(ValueError, match="checksum"):
        validate_image(content + b"changed", row["portrait"])


def test_registered_catalog_has_attribution_and_no_anonymous_assignments():
    data = read_catalog()
    assert data["candidates"]
    assert all(row["name"].lower() not in {"other", "write-in", "write-ins"} for row in data["candidates"])
    assert all(row["match_evidence"] and row["portrait"]["license"] for row in data["candidates"])


def test_house_catalog_scope_and_cross_catalog_conflicts(catalog, tmp_path):
    path, _, _ = catalog
    data = read_catalog(path)
    data['candidates'][0].update(source='call_the_map_house', race_id='FL-10')
    house = tmp_path / 'house.json'
    house.write_text(json.dumps(data))
    combined = read_catalogs((path, house))
    assert len(combined['candidates']) == 2
    assert {row['source'] for row in combined['candidates']} == {'call_the_map_senate', 'call_the_map_house'}
    with pytest.raises(ValueError, match='across catalogs'):
        read_catalogs((house, house))
    for change in ({'state_code': 'CA'}, {'source': 'unknown'}, {'name': 'Write-in'}, {'race_id': 'SEN-FL'}):
        changed = deepcopy(data)
        changed['candidates'][0].update(change)
        house.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            read_catalog(house)


def test_governor_catalog_scope_and_cross_office_conflicts(catalog, tmp_path):
    path, _, _ = catalog
    data = read_catalog(path)
    data['candidates'][0].update(source='call_the_map_governor', race_id='GOV-FL')
    governor = tmp_path / 'governor.json'
    governor.write_text(json.dumps(data))
    assert len(read_catalogs((path, governor))['candidates']) == 2
    with pytest.raises(ValueError, match='across catalogs'):
        read_catalogs((governor, governor))
    for change in ({'state_code': 'CA'}, {'source': 'unknown'}, {'name': 'Write-in'}, {'race_id': 'SEN-FL'}):
        changed = deepcopy(data)
        changed['candidates'][0].update(change)
        governor.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            read_catalog(governor)


@pytest.mark.parametrize('focus', [{'x': -1, 'y': 50, 'zoom': 2}, {'x': 50, 'y': 101, 'zoom': 2},
    {'x': 50, 'y': 50, 'zoom': 6}, {'x': 50, 'y': 50, 'zoom': float('nan')}, {'x': 50}])
def test_rejects_unsafe_portrait_focus(catalog, focus):
    path, _, _ = catalog
    data = read_catalog(path)
    data['candidates'][0]['portrait']['focus'] = focus
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='focus'):
        read_catalog(path)


def test_optional_portrait_focus_preserves_existing_api_contract(catalog):
    from app.api.media_schemas import CandidatePortrait
    _, _, row = catalog
    media = row['portrait']
    assert CandidatePortrait(**media).model_dump() == media
    focused = {**media, 'focus': {'x': 65, 'y': 44, 'zoom': 4}}
    assert CandidatePortrait(**focused).model_dump() == focused
