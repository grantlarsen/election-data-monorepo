from .core import (
    Person,
    PoliticalParty,
    Jurisdiction,
    Election,
    Contest,
    Candidacy,
    DataSource,
    ElectionResultSnapshot,
)
# Register geographic tables for metadata and integration tests.
from .geography import GeographicReference, JurisdictionIdentifier, JurisdictionRelationship, GeographicResolution
from .geography import JurisdictionBoundaryVintage, GeographicResolutionContext
from .identity import (PersonName, Organization, ExternalIdentifier, IdentityAssignmentEvent, CommitteeRelationship)

from .election import (Office, OfficeTerm, BallotLine, CanonicalResultBatch, CanonicalPublication, CanonicalVoteReturn, CanonicalMaterializationIssue)
from .state_results import StateResultBatch, StateVoteReturn, StateResultPublication
from .county_corrections import CountyCorrectionBatch, CountyVoteCorrection
from .house_returns import HouseReturnDetail, HouseDistrictReconciliation
from .candidate_identity import FecCandidateRecord, CandidateIdentityReview, CandidateFinanceSummary
from .campaign_finance import FecCommitteeRecord, FecCandidateCommitteeLink, CommitteeFiling, CommitteeFinanceSnapshot
from .senate_returns import SenateSeat, SenateContest, SenateReturnDetail, SenateContestReconciliation
