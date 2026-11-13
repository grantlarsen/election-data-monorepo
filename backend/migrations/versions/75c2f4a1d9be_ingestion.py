"""Add lossless ingestion and provenance tables.

Revision ID: 75c2f4a1d9be
Revises: 2c9541d24f1e
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "75c2f4a1d9be"
down_revision = "2c9541d24f1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_release",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("data_source.id"), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("download_url", sa.Text(), nullable=False),
        sa.Column("raw_path", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("source_id", "version", "sha256", name="uq_source_release_version_hash"),
    )
    op.create_table(
        "ingestion_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("data_source.id"), nullable=False),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("records_read", sa.Integer(), nullable=False),
        sa.Column("records_inserted", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("records_rejected", sa.Integer(), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(), nullable=False),
        sa.Column("errors_json", postgresql.JSONB(), nullable=False),
        sa.Column("options_json", postgresql.JSONB(), nullable=False),
        sa.Column("raw_sha256", sa.String(64)),
    )
    op.create_table(
        "ingestion_rejection",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("ingestion_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("reasons_json", postgresql.JSONB(), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "source_row_number", name="uq_ingestion_rejection_row"),
    )
    op.create_table(
        "election_result_observation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("row_sha256", sa.String(64), nullable=False),
        sa.Column("logical_key", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("state_raw", sa.Text()),
        sa.Column("state_code_raw", sa.Text()),
        sa.Column("state_code", sa.String(2), nullable=False),
        sa.Column("state_fips", sa.String(2), nullable=False),
        sa.Column("county_raw", sa.Text()),
        sa.Column("county_normalized", sa.Text()),
        sa.Column("county_fips_raw", sa.Text()),
        sa.Column("county_fips", sa.String(5)),
        sa.Column("office_raw", sa.Text()),
        sa.Column("candidate_raw", sa.Text()),
        sa.Column("candidate_normalized", sa.Text()),
        sa.Column("candidate_kind", sa.String(30), nullable=False),
        sa.Column("party_raw", sa.Text()),
        sa.Column("party_normalized", sa.String(200)),
        sa.Column("mode_raw", sa.Text()),
        sa.Column("mode_normalized", sa.String(100)),
        sa.Column("version_raw", sa.Text()),
        sa.Column("candidate_votes", sa.BigInteger()),
        sa.Column("total_votes", sa.BigInteger()),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id")),
        sa.Column("candidacy_id", sa.Uuid(), sa.ForeignKey("candidacy.id")),
        sa.Column("party_id", sa.Uuid(), sa.ForeignKey("political_party.id")),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("release_id", "source_row_number", name="uq_result_observation_source_row"),
        sa.CheckConstraint("year >= 2000 AND year <= 2024", name="ck_observation_year"),
        sa.CheckConstraint("candidate_votes IS NULL OR candidate_votes >= 0", name="ck_observation_votes"),
        sa.CheckConstraint("total_votes IS NULL OR total_votes >= 0", name="ck_observation_total"),
    )
    op.create_index("ix_result_observation_year_state", "election_result_observation", ["year", "state_code"])
    op.create_index("ix_result_observation_release_year", "election_result_observation", ["release_id", "year"])
    op.create_index("ix_result_observation_county", "election_result_observation", ["county_fips"])
    op.create_table(
        "source_active_year",
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("data_source.id"), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("ingestion_run.id"), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("""
        CREATE VIEW active_election_result_observation AS
        SELECT o.* FROM election_result_observation o
        JOIN source_release r ON r.id = o.release_id
        JOIN source_active_year a ON a.source_id = r.source_id
             AND a.release_id = o.release_id AND a.year = o.year
    """)


def downgrade() -> None:
    op.execute("DROP VIEW active_election_result_observation")
    op.drop_table("source_active_year")
    op.drop_index("ix_result_observation_county", table_name="election_result_observation")
    op.drop_index("ix_result_observation_release_year", table_name="election_result_observation")
    op.drop_index("ix_result_observation_year_state", table_name="election_result_observation")
    op.drop_table("election_result_observation")
    op.drop_table("ingestion_rejection")
    op.drop_table("ingestion_run")
    op.drop_table("source_release")
