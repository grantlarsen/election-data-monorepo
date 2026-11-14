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
from .identity import (PersonName, Organization, ExternalIdentifier, IdentityAssignmentEvent, CommitteeRelationship)

from .election import (Office, OfficeTerm, BallotLine, CanonicalResultBatch, CanonicalPublication, CanonicalVoteReturn, CanonicalMaterializationIssue)
