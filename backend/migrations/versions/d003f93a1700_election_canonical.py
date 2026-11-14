"""DATA-003 canonical election foundation.

Revision ID: d003f93a1700
Revises: d002a150fd10

Additive for all preexisting rows: only Candidacy.person_id nullability changes;
all added columns are nullable or have server defaults. Does not backfill guesses.
"""
from alembic import op
import sqlalchemy as sa

revision = "d003f93a1700"
down_revision = "d002a150fd10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "office",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("creation_key", sa.String(200), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id")),
        sa.Column("office_kind", sa.String(60), nullable=False),
        sa.Column("valid_from", sa.Date()), sa.Column("valid_until", sa.Date()),
        sa.UniqueConstraint("creation_key", name="uq_office_creation_key"),
        sa.CheckConstraint("valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until", name="ck_office_dates"),
    )
    op.create_index("ix_office_jurisdiction_id", "office", ["jurisdiction_id"])
    op.create_table(
        "office_term",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("creation_key", sa.String(200), nullable=False),
        sa.Column("office_id", sa.Uuid(), sa.ForeignKey("office.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("seat_label", sa.String(100)),
        sa.Column("predecessor_id", sa.Uuid(), sa.ForeignKey("office_term.id")),
        sa.UniqueConstraint("creation_key", name="uq_office_term_creation_key"),
        sa.CheckConstraint("start_date < end_date", name="ck_office_term_dates"),
    )
    op.create_index("ix_office_term_office_id", "office_term", ["office_id"])
    op.add_column("election", sa.Column("creation_key", sa.String(200)))
    op.add_column("election", sa.Column("election_cycle", sa.Integer()))
    op.add_column("election", sa.Column("parent_election_id", sa.Uuid(), sa.ForeignKey("election.id")))
    op.create_unique_constraint("uq_election_creation_key", "election", ["creation_key"])
    op.create_check_constraint("ck_election_type", "election", "election_type IN ('general','primary','runoff','special','special_primary','special_runoff','other')")
    op.add_column("contest", sa.Column("creation_key", sa.String(200)))
    op.add_column("contest", sa.Column("office_id", sa.Uuid(), sa.ForeignKey("office.id")))
    op.add_column("contest", sa.Column("office_term_id", sa.Uuid(), sa.ForeignKey("office_term.id")))
    op.add_column("contest", sa.Column("preceding_contest_id", sa.Uuid(), sa.ForeignKey("contest.id")))
    op.add_column("contest", sa.Column("nomination_party_id", sa.Uuid(), sa.ForeignKey("political_party.id")))
    op.create_unique_constraint("uq_contest_creation_key", "contest", ["creation_key"])
    op.create_index("ix_contest_office_id", "contest", ["office_id"])
    op.alter_column("candidacy", "person_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("candidacy", sa.Column("creation_key", sa.String(200)))
    op.add_column("candidacy", sa.Column("source_label", sa.Text()))
    op.add_column("candidacy", sa.Column("candidate_kind", sa.String(30), nullable=False, server_default="candidate"))
    op.create_unique_constraint("uq_candidacy_creation_key", "candidacy", ["creation_key"])
    op.create_check_constraint("ck_candidacy_kind", "candidacy", "candidate_kind IN ('candidate','write_in','aggregate','unresolved')")
    op.create_check_constraint("ck_candidacy_evidence", "candidacy", "person_id IS NOT NULL OR (source_label IS NOT NULL AND length(trim(source_label)) > 0)")
    op.create_table(
        "ballot_line",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("creation_key", sa.String(200), nullable=False),
        sa.Column("candidacy_id", sa.Uuid(), sa.ForeignKey("candidacy.id"), nullable=False),
        sa.Column("party_id", sa.Uuid(), sa.ForeignKey("political_party.id")),
        sa.Column("line_label", sa.String(200), nullable=False),
        sa.Column("line_kind", sa.String(30), nullable=False),
        sa.CheckConstraint("line_kind IN ('party','independent','write_in','unaffiliated','other')", name="ck_ballot_line_kind"),
        sa.UniqueConstraint("creation_key", name="uq_ballot_line_creation_key"),
    )
    op.create_index("ix_ballot_line_candidacy_id", "ballot_line", ["candidacy_id"])
    op.create_index("ix_ballot_line_party_id", "ballot_line", ["party_id"])
    op.create_table(
        "canonical_result_batch",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("ruleset_version", sa.String(64), nullable=False),
        sa.Column("source_release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("reference_release_id", sa.Uuid(), sa.ForeignKey("source_release.id"), nullable=False),
        sa.Column("election_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_rows", sa.Integer(), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.Column("excluded_rows", sa.Integer(), nullable=False),
        sa.Column("raw_votes_nonadditive", sa.BigInteger(), nullable=False),
        sa.Column("canonical_votes", sa.BigInteger(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("canonical_result_batch.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("scope_key", "fingerprint", name="uq_canonical_batch_scope_fingerprint"),
        sa.CheckConstraint("status IN ('COMPLETE','PARTIAL')", name="ck_canonical_batch_status"),
    )
    op.create_index("ix_canonical_result_batch_scope_key", "canonical_result_batch", ["scope_key"])
    op.create_table(
        "canonical_publication",
        sa.Column("scope_key", sa.String(200), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("canonical_result_batch.id"), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "canonical_vote_return",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("canonical_result_batch.id"), nullable=False),
        sa.Column("observation_id", sa.Uuid(), sa.ForeignKey("election_result_observation.id"), nullable=False),
        sa.Column("contest_id", sa.Uuid(), sa.ForeignKey("contest.id"), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("geographic_resolution_id", sa.Uuid(), sa.ForeignKey("geographic_resolution.id"), nullable=False),
        sa.Column("candidacy_id", sa.Uuid(), sa.ForeignKey("candidacy.id")),
        sa.Column("ballot_line_id", sa.Uuid(), sa.ForeignKey("ballot_line.id")),
        sa.Column("source_label", sa.Text(), nullable=False),
        sa.Column("reporting_level", sa.String(40), nullable=False),
        sa.Column("reporting_mode", sa.String(100), nullable=False),
        sa.Column("vote_kind", sa.String(30), nullable=False),
        sa.Column("votes", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("batch_id", "observation_id", name="uq_canonical_vote_observation"),
        sa.CheckConstraint("votes >= 0", name="ck_canonical_vote_nonnegative"),
        sa.CheckConstraint("vote_kind IN ('candidate_total','ballot_line','write_in','aggregate')", name="ck_canonical_vote_kind"),
        sa.CheckConstraint("(vote_kind = 'ballot_line') = (ballot_line_id IS NOT NULL)", name="ck_canonical_vote_line_presence"),
        sa.CheckConstraint("(vote_kind IN ('candidate_total','ballot_line') AND candidacy_id IS NOT NULL) OR (vote_kind = 'aggregate' AND candidacy_id IS NULL) OR vote_kind = 'write_in'", name="ck_canonical_vote_candidate_presence"),
    )
    op.create_index("ix_canonical_vote_return_batch_id", "canonical_vote_return", ["batch_id"])
    op.create_index("ix_canonical_return_contest_geo", "canonical_vote_return", ["contest_id", "jurisdiction_id", "reporting_mode"])
    op.create_table(
        "canonical_materialization_issue",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("canonical_result_batch.id"), nullable=False),
        sa.Column("observation_id", sa.Uuid(), sa.ForeignKey("election_result_observation.id"), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.UniqueConstraint("batch_id", "observation_id", "code", name="uq_canonical_issue_row_code"),
    )
    op.create_index("ix_canonical_issue_batch_code", "canonical_materialization_issue", ["batch_id", "code"])


def downgrade() -> None:
    # Refuse an implicit destructive downgrade when canonical results exist.
    bind = op.get_bind()
    for table in ("canonical_vote_return", "canonical_materialization_issue", "canonical_result_batch", "canonical_publication", "ballot_line", "office_term", "office"):
        if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")).scalar():
            raise RuntimeError("DATA-003 downgrade would destroy canonical history; explicitly archive/reset test data first")
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM candidacy WHERE person_id IS NULL LIMIT 1)")).scalar():
        raise RuntimeError("DATA-003 downgrade cannot restore non-null candidacy.person_id while unresolved candidacies exist")
    op.drop_index("ix_canonical_issue_batch_code", table_name="canonical_materialization_issue")
    op.drop_table("canonical_materialization_issue")
    op.drop_index("ix_canonical_return_contest_geo", table_name="canonical_vote_return")
    op.drop_index("ix_canonical_vote_return_batch_id", table_name="canonical_vote_return")
    op.drop_table("canonical_vote_return")
    op.drop_table("canonical_publication")
    op.drop_index("ix_canonical_result_batch_scope_key", table_name="canonical_result_batch")
    op.drop_table("canonical_result_batch")
    op.drop_index("ix_ballot_line_party_id", table_name="ballot_line")
    op.drop_index("ix_ballot_line_candidacy_id", table_name="ballot_line")
    op.drop_table("ballot_line")
    op.drop_constraint("ck_candidacy_evidence", "candidacy", type_="check")
    op.drop_constraint("ck_candidacy_kind", "candidacy", type_="check")
    op.drop_constraint("uq_candidacy_creation_key", "candidacy", type_="unique")
    op.drop_column("candidacy", "candidate_kind")
    op.drop_column("candidacy", "source_label")
    op.drop_column("candidacy", "creation_key")
    op.alter_column("candidacy", "person_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index("ix_contest_office_id", table_name="contest")
    op.drop_constraint("uq_contest_creation_key", "contest", type_="unique")
    for column in ("nomination_party_id", "preceding_contest_id", "office_term_id", "office_id", "creation_key"):
        op.drop_column("contest", column)
    op.drop_constraint("ck_election_type", "election", type_="check")
    op.drop_constraint("uq_election_creation_key", "election", type_="unique")
    for column in ("parent_election_id", "election_cycle", "creation_key"):
        op.drop_column("election", column)
    op.drop_index("ix_office_term_office_id", table_name="office_term")
    op.drop_table("office_term")
    op.drop_index("ix_office_jurisdiction_id", table_name="office")
    op.drop_table("office")
