"""Locally cached candidate media with source and reuse attribution."""
from pydantic import BaseModel


class CandidatePortrait(BaseModel):
    url: str
    source: str
    credit: str
    license: str
    license_url: str
    original_url: str
    download_url: str
    sha256: str
    mime_type: str
    retrieved_at: str
