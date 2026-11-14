"""Step 6.1: reviewed aliases, dated changes and append-only resolution chains.

Revision ID: b3d62a17f8ac
Revises: c1f7a2b98d40
"""
from alembic import op
import sqlalchemy as sa

revision = "b3d62a17f8ac"
down_revision = "c1f7a2b98d40"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("geographic_reference", "geoid", existing_type=sa.String(5), type_=sa.String(10), existing_nullable=False)
    op.alter_column("jurisdiction_identifier", "value", existing_type=sa.String(5), type_=sa.String(10), existing_nullable=False)
    op.drop_constraint("ck_geo_reference_kind", "geographic_reference", type_="check")
    op.create_check_constraint("ck_geo_reference_kind", "geographic_reference", "kind IN ('state', 'county', 'place')")
    op.create_table("geographic_alias",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_name", sa.String(100), nullable=False),
        sa.Column("state_code", sa.String(2), nullable=False),
        sa.Column("source_label_raw", sa.Text(), nullable=False),
        sa.Column("source_label_key", sa.Text(), nullable=False),
        sa.Column("target_geoid", sa.String(5), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id")),
        sa.Column("first_year", sa.Integer(), nullable=False),
        sa.Column("last_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("evidence_url", sa.Text(), nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=False),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_name", "state_code", "source_label_key", "target_geoid", "first_year", "last_year", name="uq_geographic_alias_scope"),
        sa.CheckConstraint("first_year <= last_year", name="ck_geographic_alias_years"),
        sa.CheckConstraint("status IN ('PROPOSED', 'APPROVED', 'REJECTED')", name="ck_geographic_alias_status"))
    op.create_index("ix_geo_alias_lookup", "geographic_alias", ["source_name", "state_code", "status"])
    op.create_table("geographic_change",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("old_geoid", sa.String(5), nullable=False),
        sa.Column("new_geoid", sa.String(5), nullable=False),
        sa.Column("old_name", sa.Text(), nullable=False),
        sa.Column("new_name", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("change_type", sa.String(40), nullable=False),
        sa.Column("evidence_url", sa.Text(), nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("verified_by", sa.String(100)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("old_geoid", "new_geoid", "effective_date", name="uq_geographic_change_event"),
        sa.CheckConstraint("old_geoid <> new_geoid", name="ck_geographic_change_distinct"),
        sa.CheckConstraint("status IN ('PROPOSED', 'VERIFIED', 'REJECTED')", name="ck_geographic_change_status"))
    op.create_table("geographic_identity_link",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("change_id", sa.Uuid(), sa.ForeignKey("geographic_change.id"), nullable=False),
        sa.Column("old_jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("new_jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("relationship", sa.String(40), nullable=False),
        sa.Column("approved_by", sa.String(100), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("change_id", "old_jurisdiction_id", "new_jurisdiction_id",name="uq_geo_identity_link"),
        sa.CheckConstraint("old_jurisdiction_id <> new_jurisdiction_id",name="ck_geo_identity_link_distinct"),
        sa.CheckConstraint("relationship IN ('SAME_ENTITY_RECODED', 'SUCCESSOR')",name="ck_geo_identity_link_relationship"))
    op.create_table("geographic_reporting_unit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_name", sa.String(100), nullable=False),
        sa.Column("state_code", sa.String(2), nullable=False),
        sa.Column("election_year", sa.Integer(), nullable=False),
        sa.Column("source_label", sa.Text(), nullable=False),
        sa.Column("identifier_scheme", sa.String(50), nullable=False),
        sa.Column("identifier_value", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id")),
        sa.Column("evidence_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_name", "state_code", "election_year", "identifier_scheme",
                            "identifier_value", name="uq_geo_reporting_unit_scope"))
    op.drop_constraint("uq_geo_resolution_observation_release", "geographic_resolution", type_="unique")
    op.add_column("geographic_resolution", sa.Column("ruleset_version", sa.String(64), nullable=False, server_default="step6-v1"))
    op.add_column("geographic_resolution", sa.Column("decision_sha256", sa.String(64)))
    op.add_column("geographic_resolution", sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("geographic_resolution.id")))
    op.add_column("geographic_resolution", sa.Column("published_by", sa.String(100)))
    op.create_unique_constraint("uq_geo_resolution_supersedes", "geographic_resolution", ["supersedes_id"])
    op.create_index("uq_geo_resolution_root", "geographic_resolution", ["observation_id", "reference_release_id"], unique=True, postgresql_where=sa.text("supersedes_id IS NULL"))
    op.create_index("ix_geo_resolution_observation_release", "geographic_resolution", ["observation_id", "reference_release_id"])


def downgrade():
    # Explicitly refuse to discard appended history or reviewed evidence.
    raise RuntimeError("Destructive Step 6.1 downgrade is intentionally unsupported; restore a database backup")
