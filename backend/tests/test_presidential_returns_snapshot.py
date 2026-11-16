"""Exercise DATA-005 snapshot against real PostgreSQL in an isolated schema."""
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.election import CanonicalResultBatch, CanonicalVoteReturn
from app.services.canonical_results import materialize_medsl_year
from app.services.presidential_returns_snapshot import snapshot
from test_data003_postgres import pg_engine, _seed, _observe


def test_readonly_snapshot_preserves_source_and_publication(pg_engine, tmp_path):
    path=tmp_path/'raw.csv';path.write_bytes(b'archived fixture')
    with Session(pg_engine) as session, session.begin():
        seed=_seed(session)
        seed['release'].raw_path=str(path)
        seed['release'].sha256=sha256(path.read_bytes()).hexdigest()
        for i,(name,votes,kind) in enumerate([
            ('BARACK OBAMA',100,'candidate'),('JOHN MCCAIN',80,'candidate'),('OTHER',5,'aggregate')],2):
            _observe(session,seed,i,name=name,votes=votes,total=185,kind=kind)
        session.execute(text('CREATE TABLE alembic_version (version_num varchar(32))'))
        session.execute(text("INSERT INTO alembic_version VALUES ('fixture')"))
    with Session(pg_engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        published=materialize_medsl_year(session,year=2008,dry_run=False)
    with Session(pg_engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        report=snapshot(session)
        assert report['read_only']=='on'
        assert report['stored_batch']['id']==published['batch_id']
        assert report['stored_batch']['fingerprint']==report['preview']['fingerprint']
        assert report['stored_batch']['canonical_votes']==185
        assert len(report['observations'])==3
        assert all(r['stored_accepted'] and r['preview_accepted'] for r in report['observations'])
        assert session.get(CanonicalResultBatch,UUID(published['batch_id'])).canonical_votes==185
        assert sum(session.scalars(select(CanonicalVoteReturn.votes)))==185
    with Session(pg_engine) as session, session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
        replay=materialize_medsl_year(session,year=2008,dry_run=False)
        assert replay['action']=='UNCHANGED' and replay['batch_id']==published['batch_id']
