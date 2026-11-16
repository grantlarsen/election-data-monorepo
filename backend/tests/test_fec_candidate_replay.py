"""Optional full pinned-file replay; never downloads sources during tests."""
from datetime import datetime, timezone
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.candidate_identity import CandidateFinanceSummary, FecCandidateRecord
from app.models.core import Person
from ingestion.fec_candidates import load, parse
from ingestion.source import sha256_file
from test_identity import identity_engine


@pytest.mark.integration
def test_full_pinned_fec_import_and_replay(identity_engine, tmp_path):
    inputs = [("master", os.getenv("FEC_CANDIDATE_MASTER_ZIP")), ("summary", os.getenv("FEC_CANDIDATE_SUMMARY_ZIP"))]
    if not all(path for _, path in inputs):
        pytest.skip("Set both FEC_CANDIDATE_MASTER_ZIP and FEC_CANDIDATE_SUMMARY_ZIP for full-file replay")
    for kind, value in inputs:
        path = Path(value)
        count = len(parse(path, kind, cycle=2024))
        options = dict(engine=identity_engine, path=path, kind=kind, cycle=2024, sha256=sha256_file(path),
            retrieved_at=datetime.now(timezone.utc), data_dir=tmp_path / "raw")
        first, second = load(**options), load(**options)
        assert first["read"] == first["inserted"] == count
        assert second["inserted"] == 0 and second["unchanged"] == count
        assert first["release_id"] == second["release_id"]
        with Session(identity_engine) as session:
            model = FecCandidateRecord if kind == "master" else CandidateFinanceSummary
            assert session.scalar(select(func.count()).select_from(model)) == count
            assert session.scalar(select(func.count()).select_from(Person)) == 0
