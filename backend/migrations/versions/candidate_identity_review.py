"""Add pinned candidate records, reviewed links and candidate finance summaries.

Revision ID: candidate_identity_review
Revises: house_return_evidence
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "candidate_identity_review"
down_revision = "house_return_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("fec_candidate_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("identifier_id", sa.Uuid(), sa.ForeignKey("external_identifier.id"), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("election_year", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("office", sa.String(1), nullable=False),
        sa.Column("state_code", sa.String(2), nullable=False),
        sa.Column("district", sa.String(2)),
        sa.Column("principal_committee", sa.String(9)),
        sa.Column("raw_json", JSONB(), nullable=False),
        sa.UniqueConstraint("release_id", "identifier_id", name="uq_fec_candidate_record"),
        sa.CheckConstraint("office IN ('H', 'S', 'P')", name="ck_fec_candidate_office"),
        sa.CheckConstraint("cycle >= 1788 AND cycle % 2 = 0", name="ck_fec_candidate_cycle"))
    op.create_index("ix_fec_candidate_scope", "fec_candidate_record", ["release_id", "election_year", "office", "state_code", "district"])
    op.create_table("candidate_identity_review",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("candidacy_id", sa.Uuid(), sa.ForeignKey("candidacy.id"), nullable=False),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("record_id", sa.Uuid(), sa.ForeignKey("fec_candidate_record.id")),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("evidence_json", JSONB(), nullable=False),
        sa.Column("actor", sa.String(150)),
        sa.Column("decision_evidence", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("dedupe_key", name="uq_candidate_review_key"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'unmatched')", name="ck_candidate_review_status"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_candidate_review_confidence"),
        sa.CheckConstraint("(status = 'unmatched') = (record_id IS NULL)", name="ck_candidate_review_record"),
        sa.CheckConstraint("status NOT IN ('accepted', 'rejected') OR (length(trim(actor)) > 0 AND actor IS NOT NULL AND length(trim(decision_evidence)) > 0 AND decision_evidence IS NOT NULL)", name="ck_candidate_review_decision"))
    op.create_index("ix_candidate_review_queue", "candidate_identity_review", ["status", "candidacy_id"])
    op.create_index("uq_candidate_review_accepted", "candidate_identity_review", ["candidacy_id"], unique=True, postgresql_where=sa.text("status = 'accepted'"))
    op.create_table("candidate_finance_summary",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("identifier_id", sa.Uuid(), sa.ForeignKey("external_identifier.id"), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("coverage_end", sa.Date()),
        *(sa.Column(name, sa.Numeric(18, 2)) for name in ("receipts", "disbursements", "transfers_from_authorized", "transfers_to_authorized", "cash_on_hand", "debts")),
        sa.Column("raw_json", JSONB(), nullable=False),
        sa.UniqueConstraint("release_id", "identifier_id", "cycle", name="uq_candidate_finance_release"),
        sa.CheckConstraint("cycle >= 1788 AND cycle % 2 = 0", name="ck_candidate_finance_cycle"))


def downgrade():
    op.drop_table("candidate_finance_summary")
    op.drop_table("candidate_identity_review")
    op.drop_table("fec_candidate_record")
