"""Extend immutable presidential state summaries to seven election years.

Revision ID: presidential_state_coverage
Revises: campaign_finance
"""
from alembic import op
import sqlalchemy as sa

revision = 'presidential_state_coverage'
down_revision = 'campaign_finance'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('ck_state_batch_year', 'ck_state_batch_scope'):
        op.drop_constraint(name, 'state_result_batch', type_='check')
    op.create_check_constraint('ck_state_batch_year', 'state_result_batch',
        'election_year IN (2000,2004,2008,2012,2016,2020,2024)')
    op.create_check_constraint('ck_state_batch_scope', 'state_result_batch',
        "scope_key = 'president:general:' || election_year::text || ':state:TOTAL'")
    for column in ('compared_source_release_id', 'compared_canonical_batch_id'):
        op.alter_column('state_result_batch', column, existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint('ck_state_batch_comparison', 'state_result_batch',
        'election_year <> 2008 OR (compared_source_release_id IS NOT NULL AND compared_canonical_batch_id IS NOT NULL)')
    op.drop_constraint('ck_state_return_bucket', 'state_vote_return', type_='check')
    op.create_check_constraint('ck_state_return_bucket', 'state_vote_return', 'length(trim(candidate_bucket)) > 0')
    for column in ('medsl_source_votes', 'medsl_county_votes', 'source_adjustment'):
        op.alter_column('state_vote_return', column, existing_type=sa.BigInteger(), nullable=True)
    op.create_check_constraint('ck_state_return_comparison', 'state_vote_return',
        '(medsl_source_votes IS NULL AND medsl_county_votes IS NULL AND source_adjustment IS NULL) OR '
        '(medsl_source_votes IS NOT NULL AND medsl_county_votes IS NOT NULL AND source_adjustment IS NOT NULL)')
    # Keep the original target/immutability triggers. Additional scope checks
    # preserve 2008's required comparison and three exact source categories.
    op.execute("""CREATE FUNCTION presidential_state_bucket() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE y integer; allowed text[];
    BEGIN
      SELECT election_year INTO y FROM state_result_batch WHERE id=NEW.batch_id;
      allowed := CASE y
        WHEN 2000 THEN ARRAY['GEORGE W. BUSH','AL GORE','OTHER']
        WHEN 2004 THEN ARRAY['GEORGE W. BUSH','JOHN KERRY','OTHER']
        WHEN 2008 THEN ARRAY['BARACK OBAMA','JOHN MCCAIN','OTHER']
        WHEN 2012 THEN ARRAY['BARACK OBAMA','MITT ROMNEY','OTHER']
        WHEN 2016 THEN ARRAY['DONALD TRUMP','HILLARY CLINTON','OTHER']
        WHEN 2020 THEN ARRAY['JOE BIDEN','DONALD TRUMP','OTHER']
        WHEN 2024 THEN ARRAY['KAMALA HARRIS','DONALD TRUMP','OTHER'] END;
      IF NOT (NEW.candidate_bucket = ANY(allowed)) OR
         (y=2008 AND (NEW.medsl_source_votes IS NULL OR NEW.medsl_county_votes IS NULL OR NEW.source_adjustment IS NULL))
      THEN RAISE EXCEPTION 'Invalid presidential source bucket/comparison'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER presidential_state_bucket BEFORE INSERT ON state_vote_return '
               'FOR EACH ROW EXECUTE FUNCTION presidential_state_bucket()')


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM state_result_batch WHERE election_year<>2008)
      THEN RAISE EXCEPTION 'Downgrade would discard presidential state history'; END IF; END $$""")
    op.execute('DROP TRIGGER presidential_state_bucket ON state_vote_return')
    op.execute('DROP FUNCTION presidential_state_bucket()')
    op.drop_constraint('ck_state_batch_comparison', 'state_result_batch', type_='check')
    op.drop_constraint('ck_state_return_comparison', 'state_vote_return', type_='check')
    for column in ('compared_source_release_id', 'compared_canonical_batch_id'):
        op.alter_column('state_result_batch', column, existing_type=sa.Uuid(), nullable=False)
    for column in ('medsl_source_votes', 'medsl_county_votes', 'source_adjustment'):
        op.alter_column('state_vote_return', column, existing_type=sa.BigInteger(), nullable=False)
    for name in ('ck_state_batch_year', 'ck_state_batch_scope'):
        op.drop_constraint(name, 'state_result_batch', type_='check')
    op.create_check_constraint('ck_state_batch_year', 'state_result_batch', 'election_year = 2008')
    op.create_check_constraint('ck_state_batch_scope', 'state_result_batch', "scope_key = 'president:general:2008:state:TOTAL'")
    op.drop_constraint('ck_state_return_bucket', 'state_vote_return', type_='check')
    op.create_check_constraint('ck_state_return_bucket', 'state_vote_return', "candidate_bucket IN ('BARACK OBAMA','JOHN MCCAIN','OTHER')")
