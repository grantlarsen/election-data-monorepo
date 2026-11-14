"""DATA-002: add canonical identity evidence and committee relationships.

Revision ID: d002a150fd10
Revises: b3d62a17f8ac

Additive migration. No existing election or geography rows are modified.
"""
from alembic import op
import sqlalchemy as sa

revision = "d002a150fd10"
down_revision = "b3d62a17f8ac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("person", sa.Column("creation_key", sa.String(200), nullable=True))
    op.create_unique_constraint("uq_person_creation_key", "person", ["creation_key"])

    op.create_table(
        "organization",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("creation_key", sa.String(200), nullable=False),
        sa.Column("party_id", sa.Uuid(), sa.ForeignKey("political_party.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('committee', 'political_organization', 'other')", name="ck_organization_kind"),
        sa.UniqueConstraint("creation_key", name="uq_organization_creation_key"),
    )
    op.create_index("ix_organization_party", "organization", ["party_id"])

    op.create_table(
        "person_name",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("person.id"), nullable=False),
        sa.Column("name_raw", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_until", sa.Date()),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("data_source.id")),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id")),
        sa.Column("source_record_key", sa.String(200)),
        sa.Column("evidence", sa.Text()),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('primary', 'alias', 'former', 'source_reported')", name="ck_person_name_kind"),
        sa.CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until", name="ck_person_name_dates"),
        sa.UniqueConstraint("dedupe_key", name="uq_person_name_dedupe"),
    )
    op.create_index("ix_person_name_person", "person_name", ["person_id"])

    op.create_table(
        "external_identifier",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("identifier_type", sa.String(50), nullable=False),
        sa.Column("value", sa.String(200), nullable=False),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("person.id")),
        sa.Column("candidacy_id", sa.Uuid(), sa.ForeignKey("candidacy.id")),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organization.id")),
        sa.Column("party_id", sa.Uuid(), sa.ForeignKey("political_party.id")),
        sa.Column("label_raw", sa.Text()),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("data_source.id"), nullable=False),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id")),
        sa.Column("source_record_key", sa.String(200)),
        sa.Column("evidence", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("namespace", "identifier_type", "value", name="uq_external_identifier_namespace_type_value"),
        sa.CheckConstraint("length(trim(value)) > 0", name="ck_external_identifier_value"),
        sa.CheckConstraint("namespace <> 'fec' OR identifier_type <> 'committee' OR (person_id IS NULL AND candidacy_id IS NULL AND party_id IS NULL)", name="ck_external_identifier_fec_committee"),
        sa.CheckConstraint("namespace <> 'fec' OR identifier_type <> 'candidate' OR (organization_id IS NULL AND party_id IS NULL)", name="ck_external_identifier_fec_candidate"),
        sa.CheckConstraint(
            "(CASE WHEN person_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN candidacy_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN organization_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN party_id IS NULL THEN 0 ELSE 1 END) <= 1",
            name="ck_external_identifier_single_target",
        ),
    )
    for name in ("person", "candidacy", "organization", "party"):
        op.create_index(f"ix_external_identifier_{name}", "external_identifier", [f"{name}_id"])

    op.create_table(
        "identity_assignment_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identifier_id", sa.Uuid(), sa.ForeignKey("external_identifier.id"), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("person.id")),
        sa.Column("candidacy_id", sa.Uuid(), sa.ForeignKey("candidacy.id")),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organization.id")),
        sa.Column("party_id", sa.Uuid(), sa.ForeignKey("political_party.id")),
        sa.Column("actor", sa.String(150), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("target_type IN ('person', 'candidacy', 'organization', 'party')", name="ck_identity_event_target_type"),
        sa.CheckConstraint(
            "(CASE WHEN person_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN candidacy_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN organization_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN party_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_identity_event_single_target",
        ),
        sa.CheckConstraint(
            "(target_type = 'person' AND person_id IS NOT NULL) OR "
            "(target_type = 'candidacy' AND candidacy_id IS NOT NULL) OR "
            "(target_type = 'organization' AND organization_id IS NOT NULL) OR "
            "(target_type = 'party' AND party_id IS NOT NULL)",
            name="ck_identity_event_target_matches_type",
        ),
    )
    op.create_index("ix_identity_event_identifier", "identity_assignment_event", ["identifier_id"])

    op.create_table(
        "committee_relationship",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("person.id")),
        sa.Column("candidacy_id", sa.Uuid(), sa.ForeignKey("candidacy.id")),
        sa.Column("role", sa.String(60), nullable=False),
        sa.Column("cycle", sa.Integer()),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_until", sa.Date()),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("data_source.id"), nullable=False),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id")),
        sa.Column("source_record_key", sa.String(200)),
        sa.Column("evidence", sa.Text()),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("dedupe_key", name="uq_committee_relationship_dedupe"),
        sa.CheckConstraint("person_id IS NOT NULL OR candidacy_id IS NOT NULL", name="ck_committee_relationship_subject"),
        sa.CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until", name="ck_committee_relationship_dates"),
        sa.CheckConstraint("cycle IS NULL OR cycle >= 1788", name="ck_committee_relationship_cycle"),
    )
    for name in ("person", "candidacy", "org"):
        op.create_index(f"ix_committee_relationship_{name}", "committee_relationship", ["organization_id" if name == "org" else f"{name}_id"])


def downgrade() -> None:
    for name in ("person", "candidacy", "org"):
        op.drop_index(f"ix_committee_relationship_{name}", table_name="committee_relationship")
    op.drop_table("committee_relationship")
    op.drop_index("ix_identity_event_identifier", table_name="identity_assignment_event")
    op.drop_table("identity_assignment_event")
    for name in ("person", "candidacy", "organization", "party"):
        op.drop_index(f"ix_external_identifier_{name}", table_name="external_identifier")
    op.drop_table("external_identifier")
    op.drop_index("ix_person_name_person", table_name="person_name")
    op.drop_table("person_name")
    op.drop_index("ix_organization_party", table_name="organization")
    op.drop_table("organization")
    op.drop_constraint("uq_person_creation_key", "person", type_="unique")
    op.drop_column("person", "creation_key")
