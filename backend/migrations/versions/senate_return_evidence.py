"""Add Senate seat classes, scope evidence and source reconciliation.

Revision ID: senate_return_evidence
Revises: presidential_state_coverage
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "senate_return_evidence"
down_revision = "presidential_state_coverage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("senate_seat",
        sa.Column("office_id", sa.Uuid(), sa.ForeignKey("office.id"), primary_key=True),
        sa.Column("state_code", sa.String(2), nullable=False),
        sa.Column("seat_class", sa.Integer(), nullable=False),
        sa.Column("evidence_url", sa.String(1000), nullable=False),
        sa.UniqueConstraint("state_code", "seat_class", name="uq_senate_seat_state_class"),
        sa.CheckConstraint("seat_class IN (1,2,3)", name="ck_senate_seat_class"),
        sa.CheckConstraint("state_code ~ '^[A-Z]{2}$' AND state_code <> 'DC'", name="ck_senate_seat_state"))
    op.create_table("senate_contest",
        sa.Column("contest_id", sa.Uuid(), sa.ForeignKey("contest.id"), primary_key=True),
        sa.Column("scope_evidence_json", JSONB(), nullable=False))
    op.create_table("senate_return_detail",
        sa.Column("observation_id", sa.Uuid(), sa.ForeignKey("election_result_observation.id"), primary_key=True),
        sa.Column("stage", sa.String(30), nullable=False),
        *(sa.Column(f, sa.Boolean(), nullable=False) for f in ("special", "writein", "unofficial")))
    op.create_table("senate_contest_reconciliation",
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("canonical_result_batch.id"), primary_key=True),
        sa.Column("source_key", sa.String(100), primary_key=True),
        sa.Column("checks_json", JSONB(), nullable=False))


def downgrade():
    op.drop_table("senate_contest_reconciliation")
    op.drop_table("senate_return_detail")
    op.drop_table("senate_contest")
    op.drop_table("senate_seat")
