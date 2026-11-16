"""DATA-005: immutable FEC-authoritative 2008 state results and precedence.

Revision ID: d005fec2008a
Revises: d004a9c21e70
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'd005fec2008a'
down_revision = 'd004a9c21e70'
branch_labels = None
depends_on = None
STATES = "'AK','AL','AR','AZ','CA','CO','CT','DC','DE','FL','GA','HI','IA','ID','IL','IN','KS','KY','LA','MA','MD','ME','MI','MN','MO','MS','MT','NC','ND','NE','NH','NJ','NM','NV','NY','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VA','VT','WA','WI','WV','WY'"


def upgrade():
    op.create_table('state_result_batch',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('scope_key',sa.String(200),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('ruleset_version',sa.String(64),nullable=False),
        sa.Column('election_year',sa.Integer(),nullable=False),
        sa.Column('source_release_id',sa.Uuid(),sa.ForeignKey('source_release.id'),nullable=False),
        sa.Column('compared_source_release_id',sa.Uuid(),sa.ForeignKey('source_release.id'),nullable=False),
        sa.Column('compared_canonical_batch_id',sa.Uuid(),sa.ForeignKey('canonical_result_batch.id'),nullable=False),
        sa.Column('published_by',sa.String(100),nullable=False),
        sa.Column('authorization_note',sa.Text(),nullable=False),
        sa.Column('manifest_json',JSONB(),nullable=False),
        sa.Column('supersedes_id',sa.Uuid()),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint('scope_key','fingerprint',name='uq_state_batch_fingerprint'),
        sa.UniqueConstraint('id','scope_key',name='uq_state_batch_scope'),
        sa.ForeignKeyConstraint(['supersedes_id','scope_key'],['state_result_batch.id','state_result_batch.scope_key'],name='fk_state_batch_predecessor_scope'),
        sa.CheckConstraint('election_year = 2008',name='ck_state_batch_year'),
        sa.CheckConstraint("scope_key = 'president:general:2008:state:TOTAL'",name='ck_state_batch_scope'),
        sa.CheckConstraint('length(trim(published_by)) > 0 AND length(trim(authorization_note)) > 0',name='ck_state_batch_authorization'),
        sa.CheckConstraint('supersedes_id IS NULL OR supersedes_id <> id',name='ck_state_batch_not_self'))
    op.create_table('state_vote_return',
        sa.Column('batch_id',sa.Uuid(),sa.ForeignKey('state_result_batch.id'),primary_key=True),
        sa.Column('state_code',sa.String(2),primary_key=True),
        sa.Column('candidate_bucket',sa.String(30),primary_key=True),
        sa.Column('jurisdiction_id',sa.Uuid(),sa.ForeignKey('jurisdiction.id'),nullable=False),
        sa.Column('contest_id',sa.Uuid(),sa.ForeignKey('contest.id'),nullable=False),
        sa.Column('votes',sa.BigInteger(),nullable=False),
        sa.Column('medsl_source_votes',sa.BigInteger(),nullable=False),
        sa.Column('medsl_county_votes',sa.BigInteger(),nullable=False),
        sa.Column('source_adjustment',sa.BigInteger(),nullable=False),
        sa.Column('source_locator',sa.Text(),nullable=False),
        sa.Column('components_json',JSONB(),nullable=False),
        sa.CheckConstraint(f'state_code IN ({STATES})',name='ck_state_return_state'),
        sa.CheckConstraint("candidate_bucket IN ('BARACK OBAMA','JOHN MCCAIN','OTHER')",name='ck_state_return_bucket'),
        sa.CheckConstraint('votes >= 0 AND medsl_source_votes >= 0 AND medsl_county_votes >= 0',name='ck_state_return_nonnegative'),
        sa.CheckConstraint('votes = medsl_source_votes + source_adjustment',name='ck_state_return_adjustment'))
    op.create_table('state_result_publication',
        sa.Column('scope_key',sa.String(200),primary_key=True),
        sa.Column('batch_id',sa.Uuid(),nullable=False),
        sa.Column('published_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.ForeignKeyConstraint(['batch_id','scope_key'],['state_result_batch.id','state_result_batch.scope_key'],name='fk_state_publication_scope'),
        sa.UniqueConstraint('batch_id',name='uq_state_publication_batch'))
    op.execute("""CREATE FUNCTION data005_state_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'DATA-005 state result history is append-only: %', TG_TABLE_NAME; END $$""")
    for table in ('state_result_batch','state_vote_return'):
        op.execute(f'CREATE TRIGGER data005_state_immutable BEFORE UPDATE OR DELETE ON {table} '
                   'FOR EACH ROW EXECUTE FUNCTION data005_state_immutable()')
    op.execute("""CREATE FUNCTION data005_state_target() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM jurisdiction j WHERE j.id=NEW.jurisdiction_id
               AND j.level='state' AND j.state_code=NEW.state_code)
          OR NOT EXISTS (SELECT 1 FROM contest c JOIN election e ON e.id=c.election_id
               JOIN state_result_batch b ON b.id=NEW.batch_id JOIN office o ON o.id=c.office_id
               WHERE c.id=NEW.contest_id AND c.jurisdiction_id=NEW.jurisdiction_id
               AND e.jurisdiction_id=NEW.jurisdiction_id AND e.election_type='general'
               AND extract(year from e.election_date)=b.election_year
               AND o.creation_key='us:federal:president')
          THEN RAISE EXCEPTION 'DATA-005 state/contest scope mismatch'; END IF;
          RETURN NEW;
        END $$""")
    op.execute('CREATE TRIGGER data005_state_target BEFORE INSERT ON state_vote_return '
               'FOR EACH ROW EXECUTE FUNCTION data005_state_target()')
    op.execute("""CREATE FUNCTION data005_state_complete() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (SELECT count(*) FROM state_vote_return WHERE batch_id=NEW.batch_id)<>153
             OR (SELECT count(DISTINCT state_code) FROM state_vote_return WHERE batch_id=NEW.batch_id)<>51
          THEN RAISE EXCEPTION 'DATA-005 requires all 51 states/DC and three buckets before publication'; END IF;
          RETURN NEW;
        END $$""")
    op.execute('CREATE TRIGGER data005_state_complete BEFORE INSERT OR UPDATE ON state_result_publication '
               'FOR EACH ROW EXECUTE FUNCTION data005_state_complete()')


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM state_result_batch)
        OR EXISTS (SELECT 1 FROM state_vote_return) OR EXISTS (SELECT 1 FROM state_result_publication)
        THEN RAISE EXCEPTION 'DATA-005 downgrade would discard authoritative result history'; END IF; END $$""")
    op.drop_table('state_result_publication')
    op.drop_table('state_vote_return')
    op.drop_table('state_result_batch')
    for name in ('data005_state_complete','data005_state_target','data005_state_immutable'):
        op.execute(f'DROP FUNCTION {name}()')
