"""Validated append-only writes and explicit-period committee finance selection.

These operations participate in the caller's transaction. Importers own release
acquisition and IngestionRun accounting; this module never commits or fetches.
"""
from datetime import date
from decimal import Decimal
import re
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy import Numeric, inspect, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.campaign_finance import (
    CommitteeFiling, CommitteeFinanceSnapshot, FecCandidateCommitteeLink,
    FecCommitteeRecord,
)
from app.models.identity import ExternalIdentifier, Organization
from app.models.ingestion import SourceRelease
from app.services.identity import IdentityConflictError

FinanceRecord = TypeVar("FinanceRecord", FecCommitteeRecord, FecCandidateCommitteeLink,
                        CommitteeFiling, CommitteeFinanceSnapshot)
_KEYS = {
    FecCommitteeRecord: ("release_id", "identifier_id", "cycle"),
    FecCandidateCommitteeLink: ("release_id", "linkage_id"),
    CommitteeFiling: ("release_id", "source_record_key"),
    CommitteeFinanceSnapshot: ("release_id", "source_record_key"),
}


def validate_cycle(cycle: int) -> None:
    if isinstance(cycle, bool) or not isinstance(cycle, int) or not 1788 <= cycle <= 9998 or cycle % 2:
        raise ValueError("FEC cycle must be an even year between 1788 and 9998")


def cycle_for_date(value: date) -> int:
    cycle = value.year + value.year % 2
    validate_cycle(cycle)
    return cycle


def _identifier(session: Session, identifier_id: UUID, kind: str) -> ExternalIdentifier:
    row = session.get(ExternalIdentifier, identifier_id)
    pattern = r"C[0-9]{8}" if kind == "committee" else r"[HSP][0-9A-Z]{8}"
    if row is None or row.namespace != "fec" or row.identifier_type != kind or not re.fullmatch(pattern, row.value):
        raise ValueError(f"Expected a valid FEC {kind} identifier")
    if kind == "committee" and row.organization_id is not None:
        organization = session.get(Organization, row.organization_id)
        if organization is None or organization.kind != "committee":
            raise IdentityConflictError("FEC committee identifier targets a non-committee organization")
    return row


def _validate(session: Session, record: FinanceRecord) -> None:
    validate_cycle(record.cycle)
    if session.get(SourceRelease, record.release_id) is None:
        raise ValueError("Source release not found")
    if not isinstance(record.raw_json, dict):
        raise ValueError("raw_json must preserve the original source record")
    if isinstance(record, FecCommitteeRecord):
        _identifier(session, record.identifier_id, "committee")
        if not record.name or not record.name.strip():
            raise ValueError("Committee name cannot be blank")
    elif isinstance(record, FecCandidateCommitteeLink):
        _identifier(session, record.candidate_identifier_id, "candidate")
        if record.committee_identifier_id is not None:
            _identifier(session, record.committee_identifier_id, "committee")
        if not isinstance(record.election_year, int) or not 1788 <= record.election_year <= 9999:
            raise ValueError("Invalid candidate election year")
    else:
        _identifier(session, record.committee_identifier_id, "committee")
        if not record.source_record_key or not record.source_record_key.strip():
            raise ValueError("source_record_key cannot be blank")
        start, end = record.coverage_start, record.coverage_end
        if start is not None and end is not None and start > end:
            raise ValueError("Coverage start is later than coverage end")
        if isinstance(record, CommitteeFiling):
            if not record.form_type or not record.form_type.strip():
                raise ValueError("form_type cannot be blank")
            if record.receipt_date is not None and record.receipt_date.utcoffset() is None:
                raise ValueError("receipt_date must include timezone")
            if record.supersedes_id is not None:
                previous = session.get(CommitteeFiling, record.supersedes_id)
                if previous is None or previous.committee_identifier_id != record.committee_identifier_id or previous.cycle != record.cycle:
                    raise IdentityConflictError("Filing predecessor has a different committee or cycle")
                # Coverage dates can be corrected by an amendment. Do not infer
                # lineage solely from equal dates, report codes or receipt order.
                if record.previous_file_number is not None and previous.file_number != record.previous_file_number:
                    raise IdentityConflictError("Filing predecessor does not match previous_file_number")
        else:
            if start is None or end is None or record.period_kind not in {"report", "cycle"}:
                raise ValueError("Finance snapshot requires coverage dates and report/cycle period_kind")
            if record.period_kind == "cycle":
                if record.filing_id is not None or start < date(record.cycle - 1, 1, 1) or end > date(record.cycle, 12, 31):
                    raise ValueError("Cycle snapshot must be within its two-year cycle and have no individual filing")
            else:
                filing = session.get(CommitteeFiling, record.filing_id) if record.filing_id else None
                scope = ("release_id", "committee_identifier_id", "cycle", "coverage_start", "coverage_end")
                if filing is None or any(getattr(filing, key) != getattr(record, key) for key in scope):
                    raise IdentityConflictError("Report snapshot does not match its filing scope and coverage")
            if record.supersedes_id is not None:
                previous = session.get(CommitteeFinanceSnapshot, record.supersedes_id)
                scope = ("committee_identifier_id", "cycle", "period_kind", "coverage_start", "coverage_end")
                if previous is None or any(getattr(previous, key) != getattr(record, key) for key in scope):
                    raise IdentityConflictError("Snapshot predecessor has a different financial scope")
    for column in record.__table__.columns:
        if isinstance(column.type, Numeric):
            amount = getattr(record, column.name)
            if amount is not None and (
                not isinstance(amount, Decimal) or not amount.is_finite()
                or abs(amount) >= Decimal("10000000000000000")
                or amount != amount.quantize(Decimal("0.01"))
            ):
                raise ValueError(f"{column.name} must be a finite Decimal fitting NUMERIC(18,2)")


def store_finance_record(session: Session, record: FinanceRecord) -> tuple[FinanceRecord, bool]:
    """Return (stored record, inserted). A changed replay is an explicit conflict.

    Pass a transient ORM object. Corrections require new release/source keys and
    may cite an earlier record using supersedes_id. No stored payload is updated.
    """
    model = type(record)
    if model not in _KEYS:
        raise TypeError("Unsupported finance record")
    if not inspect(record).transient:
        raise ValueError("Finance writes require a transient record; stored observations cannot be updated")
    _validate(session, record)
    values = {column.name: getattr(record, column.name) for column in model.__table__.columns if column.name != "id"}
    keys = _KEYS[model]
    new_id = session.scalar(insert(model).values(id=uuid4(), **values)
        .on_conflict_do_nothing(index_elements=list(keys)).returning(model.id))
    if new_id is not None:
        return session.get(model, new_id), True
    existing = session.scalar(select(model).filter_by(**{key: values[key] for key in keys}))
    if any(getattr(existing, key) != value for key, value in values.items()):
        raise IdentityConflictError("Finance source key already contains a different payload; preserve corrections in a new release")
    return existing, False


def committee_finance(session: Session, *, release_id: UUID, committee_identifier_id: UUID,
                      cycle: int, coverage_start: date, coverage_end: date,
                      period_kind: str = "cycle") -> dict:
    """Select one exact-period official snapshot; never sum committees or versions.

    A pinned report is usable only when its source explicitly says it has not
    been amended. Multiple surviving observations return ambiguity, even when
    their amounts agree. A cycle summary is already cumulative, never a report.
    """
    validate_cycle(cycle)
    if period_kind not in {"report", "cycle"} or coverage_start > coverage_end:
        raise ValueError("Invalid financial period")
    _identifier(session, committee_identifier_id, "committee")
    rows = session.scalars(select(CommitteeFinanceSnapshot).where(
        CommitteeFinanceSnapshot.release_id == release_id,
        CommitteeFinanceSnapshot.committee_identifier_id == committee_identifier_id,
        CommitteeFinanceSnapshot.cycle == cycle,
        CommitteeFinanceSnapshot.period_kind == period_kind,
        CommitteeFinanceSnapshot.coverage_start == coverage_start,
        CommitteeFinanceSnapshot.coverage_end == coverage_end)).all()
    # Search successors by predecessor ID, including corrected coverage dates.
    # Do not materialize every amendment from a potentially large release.
    superseded_snapshots = set(session.scalars(select(CommitteeFinanceSnapshot.supersedes_id).where(
        CommitteeFinanceSnapshot.release_id == release_id,
        CommitteeFinanceSnapshot.supersedes_id.in_([row.id for row in rows]))))
    eligible = [row for row in rows if row.id not in superseded_snapshots]
    unverified = False
    if period_kind == "report":
        superseded_filings = set(session.scalars(select(CommitteeFiling.supersedes_id).where(
            CommitteeFiling.release_id == release_id,
            CommitteeFiling.supersedes_id.in_([row.filing_id for row in rows]))))
        candidates = []
        for row in eligible:
            filing = session.get(CommitteeFiling, row.filing_id)
            if filing.id not in superseded_filings and filing.is_amended is False:
                candidates.append(row)
            elif filing.id not in superseded_filings and filing.is_amended is None:
                unverified = True
        eligible = candidates
    result = dict(status="ambiguous" if len(eligible) > 1 else "unverified" if unverified else "missing",
        cycle=cycle, period_kind=period_kind, coverage_start=coverage_start, coverage_end=coverage_end,
        currency="USD", total_raised=None, total_spent=None, release_id=release_id,
        committee_identifier_id=committee_identifier_id)
    if len(eligible) != 1 or unverified:
        return result
    row = eligible[0]
    result.update(status="available" if row.receipts is not None and row.disbursements is not None else "partial",
        total_raised=row.receipts, total_spent=row.disbursements,
        cash_on_hand_begin=row.cash_on_hand_begin, cash_on_hand_end=row.cash_on_hand_end,
        debts_owed_by=row.debts_owed_by, debts_owed_to=row.debts_owed_to,
        transfers_from_authorized=row.transfers_from_authorized,
        transfers_to_authorized=row.transfers_to_authorized,
        independent_expenditures=row.independent_expenditures,
        definition="reported_committee_totals", snapshot_id=row.id, release_id=row.release_id,
        filing_id=row.filing_id)
    return result
