"""Reviewed county corrections with immutable canonical supersession.

Revision ID: d005county01
Revises: d005fec2008a
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='d005county01'
down_revision='d005fec2008a'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('county_correction_batch',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('election_year',sa.Integer(),nullable=False),
        sa.Column('source_release_id',sa.Uuid(),sa.ForeignKey('source_release.id'),nullable=False),
        sa.Column('compared_source_release_id',sa.Uuid(),sa.ForeignKey('source_release.id'),nullable=False),
        sa.Column('compared_canonical_batch_id',sa.Uuid(),sa.ForeignKey('canonical_result_batch.id'),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('review_sha256',sa.String(64),nullable=False),
        sa.Column('correction_count',sa.Integer(),nullable=False),
        sa.Column('vote_adjustment',sa.BigInteger(),nullable=False),
        sa.Column('published_by',sa.String(100),nullable=False),
        sa.Column('authorization_note',sa.Text(),nullable=False),
        sa.Column('manifest_json',JSONB(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint('fingerprint',name='uq_county_correction_fingerprint'),
        sa.CheckConstraint('election_year=2008',name='ck_county_correction_year'),
        sa.CheckConstraint('correction_count>0',name='ck_county_correction_count'),
        sa.CheckConstraint('length(trim(published_by))>0 AND length(trim(authorization_note))>0',name='ck_county_correction_actor'))
    op.create_table('county_vote_correction',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('batch_id',sa.Uuid(),sa.ForeignKey('county_correction_batch.id'),nullable=False),
        sa.Column('observation_id',sa.Uuid(),sa.ForeignKey('election_result_observation.id'),nullable=False),
        sa.Column('geographic_resolution_id',sa.Uuid(),sa.ForeignKey('geographic_resolution.id'),nullable=False),
        sa.Column('row_sha256',sa.String(64),nullable=False),
        sa.Column('original_votes',sa.BigInteger(),nullable=False),
        sa.Column('votes',sa.BigInteger(),nullable=False),
        sa.Column('state_code',sa.String(2),nullable=False),
        sa.Column('candidate_bucket',sa.String(30),nullable=False),
        sa.Column('evidence_json',JSONB(),nullable=False),
        sa.UniqueConstraint('batch_id','observation_id',name='uq_county_correction_observation'),
        sa.CheckConstraint('original_votes>=0 AND votes>=0 AND original_votes<>votes',name='ck_county_correction_votes'))
    op.add_column('canonical_result_batch',sa.Column('correction_batch_id',sa.Uuid(),nullable=True))
    op.create_foreign_key('fk_canonical_correction_batch','canonical_result_batch','county_correction_batch',['correction_batch_id'],['id'])
    op.add_column('canonical_vote_return',sa.Column('correction_id',sa.Uuid(),sa.ForeignKey('county_vote_correction.id'),nullable=True))
    op.execute("""CREATE FUNCTION data005_county_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'DATA-005 county/canonical history is append-only: %',TG_TABLE_NAME; END $$""")
    for table in ('county_correction_batch','county_vote_correction','canonical_result_batch','canonical_vote_return','canonical_materialization_issue'):
        op.execute(f'CREATE TRIGGER data005_county_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION data005_county_immutable()')
    op.execute("""CREATE FUNCTION data005_county_target() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NOT EXISTS (SELECT 1 FROM county_correction_batch b
          JOIN election_result_observation o ON o.id=NEW.observation_id
          JOIN geographic_resolution g ON g.id=NEW.geographic_resolution_id
          JOIN geographic_reference r ON r.id=g.reference_id
          WHERE b.id=NEW.batch_id AND b.election_year=o.year AND o.year=2008
          AND o.release_id=b.compared_source_release_id AND o.row_sha256=NEW.row_sha256
          AND o.candidate_votes=NEW.original_votes AND o.state_code=NEW.state_code
          AND o.candidate_normalized=NEW.candidate_bucket AND o.mode_normalized='TOTAL'
          AND g.observation_id=o.id AND g.status IN ('RESOLVED','RESOLVED_ALIAS','RESOLVED_HISTORICAL')
          AND r.kind='county' AND r.jurisdiction_id=g.jurisdiction_id
          AND NOT EXISTS(SELECT 1 FROM geographic_resolution child WHERE child.supersedes_id=g.id)
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(b.manifest_json->'rows') x
             WHERE x->>'observation_id'=NEW.observation_id::text
             AND x->>'geographic_resolution_id'=NEW.geographic_resolution_id::text
             AND x->>'row_sha256'=NEW.row_sha256 AND (x->>'original_votes')::bigint=NEW.original_votes
             AND (x->>'votes')::bigint=NEW.votes AND x->>'state_code'=NEW.state_code
             AND x->>'candidate_bucket'=NEW.candidate_bucket AND x->'evidence_json'=NEW.evidence_json))
        THEN RAISE EXCEPTION 'County correction source/geography/manifest mismatch'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER data005_county_target BEFORE INSERT ON county_vote_correction FOR EACH ROW EXECUTE FUNCTION data005_county_target()')
    op.execute("""CREATE FUNCTION data005_county_return() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.correction_id IS NULL THEN
          IF EXISTS(SELECT 1 FROM canonical_result_batch b JOIN county_vote_correction x
            ON x.batch_id=b.correction_batch_id AND x.observation_id=NEW.observation_id WHERE b.id=NEW.batch_id)
            OR NOT EXISTS(SELECT 1 FROM election_result_observation o WHERE o.id=NEW.observation_id AND o.candidate_votes=NEW.votes)
          THEN RAISE EXCEPTION 'Missing correction lineage or raw vote mismatch'; END IF;
        ELSIF NOT EXISTS(SELECT 1 FROM county_vote_correction x JOIN canonical_result_batch b
          ON b.correction_batch_id=x.batch_id JOIN geographic_resolution g ON g.id=x.geographic_resolution_id
          WHERE x.id=NEW.correction_id AND b.id=NEW.batch_id AND b.election_year=2008
          AND x.observation_id=NEW.observation_id AND x.geographic_resolution_id=NEW.geographic_resolution_id
          AND g.jurisdiction_id=NEW.jurisdiction_id AND x.votes=NEW.votes)
        THEN RAISE EXCEPTION 'Invalid canonical correction lineage'; END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER data005_county_return BEFORE INSERT ON canonical_vote_return FOR EACH ROW EXECUTE FUNCTION data005_county_return()')
    op.execute("""CREATE FUNCTION data005_county_complete() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE b canonical_result_batch; c county_correction_batch;
      BEGIN
        SELECT * INTO b FROM canonical_result_batch WHERE id=NEW.batch_id;
        IF b.correction_batch_id IS NOT NULL THEN
          SELECT * INTO c FROM county_correction_batch WHERE id=b.correction_batch_id;
          IF b.election_year<>2008 OR b.status<>'PARTIAL'
            OR (SELECT count(*) FROM county_vote_correction WHERE batch_id=c.id)<>c.correction_count
            OR (SELECT count(*) FROM canonical_vote_return WHERE batch_id=b.id AND correction_id IS NOT NULL)<>c.correction_count
            OR (SELECT count(*) FROM canonical_vote_return WHERE batch_id=b.id)<>b.accepted_rows
            OR (SELECT sum(votes) FROM canonical_vote_return WHERE batch_id=b.id)<>b.canonical_votes
          THEN RAISE EXCEPTION 'Incomplete corrected canonical publication'; END IF;
        END IF;
        RETURN NEW;
      END $$""")
    op.execute('CREATE TRIGGER data005_county_complete BEFORE INSERT OR UPDATE ON canonical_publication FOR EACH ROW EXECUTE FUNCTION data005_county_complete()')


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS(SELECT 1 FROM county_correction_batch)')):
        raise RuntimeError('Cannot destroy county correction history')
    op.execute('DROP TRIGGER data005_county_complete ON canonical_publication')
    op.execute('DROP FUNCTION data005_county_complete()')
    op.execute('DROP TRIGGER data005_county_return ON canonical_vote_return')
    op.execute('DROP FUNCTION data005_county_return()')
    op.execute('DROP TRIGGER data005_county_target ON county_vote_correction')
    op.execute('DROP FUNCTION data005_county_target()')
    for t in ('county_correction_batch','county_vote_correction','canonical_result_batch','canonical_vote_return','canonical_materialization_issue'):
        op.execute(f'DROP TRIGGER data005_county_immutable ON {t}')
    op.execute('DROP FUNCTION data005_county_immutable()')
    op.drop_column('canonical_vote_return','correction_id')
    op.drop_constraint('fk_canonical_correction_batch','canonical_result_batch',type_='foreignkey')
    op.drop_column('canonical_result_batch','correction_batch_id')
    op.drop_table('county_vote_correction')
    op.drop_table('county_correction_batch')
