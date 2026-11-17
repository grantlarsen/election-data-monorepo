"""Locally cached candidate media with source and reuse attribution."""
from typing import Any

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer


class PortraitFocus(BaseModel):
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    zoom: float = Field(ge=1, le=5)


class CandidatePortrait(BaseModel):
    focus: PortraitFocus | None = None
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

    @model_serializer(mode="wrap")
    def serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if self.focus is None:
            data.pop("focus", None)
        return data
