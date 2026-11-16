"""Add versioned committee records, source linkages, filings and financial snapshots.

Revision ID: campaign_finance
Revises: candidate_identity_review
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "campaign_finance"
down_revision = "candidate_identity_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fec_committee_record',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('release_id', sa.Uuid(), nullable=False),
    sa.Column('identifier_id', sa.Uuid(), nullable=False),
    sa.Column('cycle', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=250), nullable=False),
    sa.Column('committee_type', sa.String(length=1), nullable=True),
    sa.Column('designation', sa.String(length=1), nullable=True),
    sa.Column('filing_frequency', sa.String(length=1), nullable=True),
    sa.Column('organization_type', sa.String(length=1), nullable=True),
    sa.Column('raw_json', postgresql.JSONB(), nullable=False),
    sa.CheckConstraint('cycle BETWEEN 1788 AND 9998 AND cycle % 2 = 0', name='ck_fec_committee_cycle'),
    sa.CheckConstraint('length(trim(name)) > 0', name='ck_fec_committee_name'),
    sa.ForeignKeyConstraint(['identifier_id'], ['external_identifier.id'], ),
    sa.ForeignKeyConstraint(['release_id'], ['source_release.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('release_id', 'identifier_id', 'cycle', name='uq_fec_committee_release_cycle')
    )
    op.create_index('ix_fec_committee_identifier_cycle', 'fec_committee_record', ['identifier_id', 'cycle'], unique=False)
    op.create_table('fec_candidate_committee_link',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('release_id', sa.Uuid(), nullable=False),
    sa.Column('linkage_id', sa.BigInteger(), nullable=False),
    sa.Column('candidate_identifier_id', sa.Uuid(), nullable=False),
    sa.Column('committee_identifier_id', sa.Uuid(), nullable=True),
    sa.Column('cycle', sa.Integer(), nullable=False),
    sa.Column('election_year', sa.Integer(), nullable=False),
    sa.Column('committee_type', sa.String(length=1), nullable=True),
    sa.Column('designation', sa.String(length=1), nullable=True),
    sa.Column('raw_json', postgresql.JSONB(), nullable=False),
    sa.CheckConstraint('cycle BETWEEN 1788 AND 9998 AND cycle % 2 = 0', name='ck_fec_committee_link_cycle'),
    sa.CheckConstraint('election_year BETWEEN 1788 AND 9999', name='ck_fec_committee_link_election_year'),
    sa.CheckConstraint('linkage_id > 0', name='ck_fec_committee_link_number'),
    sa.ForeignKeyConstraint(['candidate_identifier_id'], ['external_identifier.id'], ),
    sa.ForeignKeyConstraint(['committee_identifier_id'], ['external_identifier.id'], ),
    sa.ForeignKeyConstraint(['release_id'], ['source_release.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('release_id', 'linkage_id', name='uq_fec_committee_link_release')
    )
    op.create_index('ix_fec_committee_link_candidate_cycle', 'fec_candidate_committee_link', ['candidate_identifier_id', 'cycle'], unique=False)
    op.create_index('ix_fec_committee_link_committee_cycle', 'fec_candidate_committee_link', ['committee_identifier_id', 'cycle'], unique=False)
    op.create_table('committee_filing',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('release_id', sa.Uuid(), nullable=False),
    sa.Column('source_record_key', sa.String(length=200), nullable=False),
    sa.Column('committee_identifier_id', sa.Uuid(), nullable=False),
    sa.Column('cycle', sa.Integer(), nullable=False),
    sa.Column('file_number', sa.BigInteger(), nullable=True),
    sa.Column('previous_file_number', sa.BigInteger(), nullable=True),
    sa.Column('supersedes_id', sa.Uuid(), nullable=True),
    sa.Column('form_type', sa.String(length=10), nullable=False),
    sa.Column('report_type', sa.String(length=10), nullable=True),
    sa.Column('amendment_indicator', sa.String(length=1), nullable=True),
    sa.Column('is_amended', sa.Boolean(), nullable=True),
    sa.Column('receipt_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('coverage_start', sa.Date(), nullable=True),
    sa.Column('coverage_end', sa.Date(), nullable=True),
    sa.Column('raw_json', postgresql.JSONB(), nullable=False),
    sa.CheckConstraint('coverage_start IS NULL OR coverage_end IS NULL OR coverage_start <= coverage_end', name='ck_committee_filing_dates'),
    sa.CheckConstraint('cycle BETWEEN 1788 AND 9998 AND cycle % 2 = 0', name='ck_committee_filing_cycle'),
    sa.CheckConstraint('file_number IS NULL OR file_number > 0', name='ck_committee_filing_number'),
    sa.CheckConstraint('length(trim(source_record_key)) > 0', name='ck_committee_filing_source_key'),
    sa.CheckConstraint('previous_file_number IS NULL OR previous_file_number > 0', name='ck_committee_filing_previous_number'),
    sa.CheckConstraint('supersedes_id IS NULL OR supersedes_id <> id', name='ck_committee_filing_not_self'),
    sa.ForeignKeyConstraint(['committee_identifier_id'], ['external_identifier.id'], ),
    sa.ForeignKeyConstraint(['release_id'], ['source_release.id'], ),
    sa.ForeignKeyConstraint(['supersedes_id', 'committee_identifier_id', 'cycle'], ['committee_filing.id', 'committee_filing.committee_identifier_id', 'committee_filing.cycle'], name='fk_committee_filing_predecessor'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'committee_identifier_id', 'cycle', 'release_id', 'coverage_start', 'coverage_end', name='uq_committee_filing_scope'),
    sa.UniqueConstraint('id', 'committee_identifier_id', 'cycle', name='uq_committee_filing_lineage_scope'),
    sa.UniqueConstraint('release_id', 'source_record_key', name='uq_committee_filing_source_record'),
    sa.UniqueConstraint('release_id', 'file_number', name='uq_committee_filing_release_number')
    )
    op.create_index('ix_committee_filing_committee_cycle', 'committee_filing', ['committee_identifier_id', 'cycle'], unique=False)
    op.create_index('ix_committee_filing_file_number', 'committee_filing', ['file_number'], unique=False)
    op.create_index('ix_committee_filing_supersedes', 'committee_filing', ['supersedes_id'], unique=False)
    op.create_table('committee_finance_snapshot',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('release_id', sa.Uuid(), nullable=False),
    sa.Column('source_record_key', sa.String(length=200), nullable=False),
    sa.Column('committee_identifier_id', sa.Uuid(), nullable=False),
    sa.Column('cycle', sa.Integer(), nullable=False),
    sa.Column('period_kind', sa.String(length=10), nullable=False),
    sa.Column('coverage_start', sa.Date(), nullable=False),
    sa.Column('coverage_end', sa.Date(), nullable=False),
    sa.Column('filing_id', sa.Uuid(), nullable=True),
    sa.Column('supersedes_id', sa.Uuid(), nullable=True),
    sa.Column('receipts', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('disbursements', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('cash_on_hand_begin', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('cash_on_hand_end', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('debts_owed_by', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('debts_owed_to', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('transfers_from_authorized', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('transfers_to_authorized', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('independent_expenditures', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('raw_json', postgresql.JSONB(), nullable=False),
    sa.CheckConstraint("(period_kind = 'report') = (filing_id IS NOT NULL)", name='ck_committee_finance_filing_kind'),
    sa.CheckConstraint("period_kind <> 'cycle' OR (coverage_start >= make_date(cycle - 1, 1, 1) AND coverage_end <= make_date(cycle, 12, 31))", name='ck_committee_finance_cycle_dates'),
    sa.CheckConstraint("period_kind IN ('report', 'cycle')", name='ck_committee_finance_period_kind'),
    sa.CheckConstraint('coverage_start <= coverage_end', name='ck_committee_finance_dates'),
    sa.CheckConstraint('cycle BETWEEN 1788 AND 9998 AND cycle % 2 = 0', name='ck_committee_finance_cycle'),
    sa.CheckConstraint('length(trim(source_record_key)) > 0', name='ck_committee_finance_source_key'),
    sa.CheckConstraint('supersedes_id IS NULL OR supersedes_id <> id', name='ck_committee_finance_not_self'),
    sa.ForeignKeyConstraint(['committee_identifier_id'], ['external_identifier.id'], ),
    sa.ForeignKeyConstraint(['filing_id', 'committee_identifier_id', 'cycle', 'release_id', 'coverage_start', 'coverage_end'], ['committee_filing.id', 'committee_filing.committee_identifier_id', 'committee_filing.cycle', 'committee_filing.release_id', 'committee_filing.coverage_start', 'committee_filing.coverage_end'], name='fk_committee_finance_filing_scope'),
    sa.ForeignKeyConstraint(['release_id'], ['source_release.id'], ),
    sa.ForeignKeyConstraint(['supersedes_id', 'committee_identifier_id', 'cycle', 'period_kind', 'coverage_start', 'coverage_end'], ['committee_finance_snapshot.id', 'committee_finance_snapshot.committee_identifier_id', 'committee_finance_snapshot.cycle', 'committee_finance_snapshot.period_kind', 'committee_finance_snapshot.coverage_start', 'committee_finance_snapshot.coverage_end'], name='fk_committee_finance_predecessor'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('filing_id', name='uq_committee_finance_filing'),
    sa.UniqueConstraint('id', 'committee_identifier_id', 'cycle', 'period_kind', 'coverage_start', 'coverage_end', name='uq_committee_finance_lineage_scope'),
    sa.UniqueConstraint('release_id', 'source_record_key', name='uq_committee_finance_source_record')
    )
    op.create_index('ix_committee_finance_scope', 'committee_finance_snapshot', ['committee_identifier_id', 'cycle', 'release_id', 'period_kind'], unique=False)
    op.create_index('ix_committee_finance_supersedes', 'committee_finance_snapshot', ['supersedes_id'], unique=False)
    op.create_check_constraint("ck_committee_relationship_two_year_cycle", "committee_relationship", "cycle IS NULL OR (cycle <= 9998 AND cycle % 2 = 0)")


def downgrade():
    op.drop_constraint("ck_committee_relationship_two_year_cycle", "committee_relationship", type_="check")
    op.drop_table("committee_finance_snapshot")
    op.drop_table("committee_filing")
    op.drop_table("fec_candidate_committee_link")
    op.drop_table("fec_committee_record")
