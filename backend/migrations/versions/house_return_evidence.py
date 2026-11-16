"""Preserve House source semantics and district reconciliation evidence.

Revision ID: house_return_evidence
Revises: d005county01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "house_return_evidence"
down_revision = "d005county01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("house_return_detail",
        sa.Column("observation_id", sa.Uuid(), sa.ForeignKey("election_result_observation.id"), primary_key=True),
        sa.Column("district_code", sa.String(2), nullable=False),
        sa.Column("stage", sa.String(10), nullable=False),
        *(sa.Column(name, sa.Boolean(), nullable=False) for name in
          ("special", "runoff", "writein", "unofficial", "fusion_ticket")),
        sa.Column("flags_json", JSONB(), nullable=False),
        sa.CheckConstraint("district_code ~ '^[0-9]{2}$'", name="ck_house_district_code"),
        sa.CheckConstraint("stage IN ('GEN', 'PRI', 'RUNOFF')", name="ck_house_stage"))
    op.create_table("house_district_reconciliation",
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("canonical_result_batch.id"), primary_key=True),
        sa.Column("geoid", sa.String(4), primary_key=True),
        sa.Column("source_rows", sa.Integer(), nullable=False),
        sa.Column("reported_total", sa.BigInteger()),
        sa.Column("source_category_sum", sa.BigInteger(), nullable=False),
        sa.Column("canonical_votes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("checks_json", JSONB(), nullable=False),
        sa.CheckConstraint("geoid ~ '^[0-9]{4}$'", name="ck_house_reconciliation_geoid"),
        sa.CheckConstraint("source_rows > 0 AND canonical_votes >= 0", name="ck_house_reconciliation_counts"),
        sa.CheckConstraint("status IN ('RECONCILED', 'EXCLUDED')", name="ck_house_reconciliation_status"))


def downgrade():
    op.drop_table("house_district_reconciliation")
    op.drop_table("house_return_detail")
