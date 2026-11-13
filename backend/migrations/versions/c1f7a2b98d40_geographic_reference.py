"""Versioned geographic reference and append-only resolution decisions.

Revision ID: c1f7a2b98d40
Revises: 75c2f4a1d9be
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c1f7a2b98d40"
down_revision = "75c2f4a1d9be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geographic_reference",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("geoid", sa.String(5), nullable=False),
        sa.Column("state_fips", sa.String(2), nullable=False),
        sa.Column("name_raw", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("vintage_start", sa.Integer(), nullable=False),
        sa.Column("vintage_end", sa.Integer(), nullable=False),
        sa.Column("source_row_number", sa.Integer()),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("release_id", "kind", "geoid", name="uq_geo_reference_release_kind_geoid"),
        sa.CheckConstraint("vintage_start <= vintage_end", name="ck_geo_reference_vintage"),
        sa.CheckConstraint("kind IN ('state', 'county')", name="ck_geo_reference_kind"),
    )
    op.create_index("ix_geographic_reference_release_id", "geographic_reference", ["release_id"])
    op.create_index("ix_geographic_reference_jurisdiction_id", "geographic_reference", ["jurisdiction_id"])
    op.create_index("ix_geo_reference_vintage_code", "geographic_reference", ["vintage_start", "vintage_end", "geoid"])
    op.create_table(
        "jurisdiction_identifier",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("reference_id", sa.Uuid(), sa.ForeignKey("geographic_reference.id"), nullable=False),
        sa.Column("scheme", sa.String(30), nullable=False),
        sa.Column("value", sa.String(5), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_until", sa.Date()),
        sa.UniqueConstraint("reference_id", "scheme", name="uq_jurisdiction_identifier_reference_scheme"),
        sa.CheckConstraint("valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from", name="ck_jurisdiction_identifier_dates"),
    )
    op.create_index("ix_jurisdiction_identifier_scheme_value", "jurisdiction_identifier", ["scheme", "value"])
    op.create_table(
        "jurisdiction_relationship",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("child_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("reference_id", sa.Uuid(), sa.ForeignKey("geographic_reference.id"), nullable=False),
        sa.Column("relationship", sa.String(30), nullable=False),
        sa.UniqueConstraint("reference_id", name="uq_jurisdiction_relationship_reference"),
    )
    op.create_table(
        "geographic_resolution",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("observation_id", sa.Uuid(), sa.ForeignKey("election_result_observation.id"), nullable=False),
        sa.Column("reference_release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("reference_id", sa.Uuid(), sa.ForeignKey("geographic_reference.id")),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("method", sa.String(60), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("observation_id", "reference_release_id", name="uq_geo_resolution_observation_release"),
    )
    op.create_index("ix_geo_resolution_release_status", "geographic_resolution", ["reference_release_id", "status"])


def downgrade() -> None:
    op.drop_table("geographic_resolution")
    op.drop_table("jurisdiction_relationship")
    op.drop_table("jurisdiction_identifier")
    op.drop_index("ix_geo_reference_vintage_code", table_name="geographic_reference")
    op.drop_index("ix_geographic_reference_jurisdiction_id", table_name="geographic_reference")
    op.drop_index("ix_geographic_reference_release_id", table_name="geographic_reference")
    op.drop_table("geographic_reference")
