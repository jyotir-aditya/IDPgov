"""Extraction provider interface + result models.

Provider is selected by AI_PROVIDER env var. Add a new provider = one new file
that implements ExtractionProvider.
"""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


Position = Literal[
    "TOP_LEFT", "TOP_CENTER", "TOP_RIGHT",
    "BODY",
    "BOTTOM_LEFT", "BOTTOM_CENTER", "BOTTOM_RIGHT",
    "UNKNOWN",
]


class Candidate(BaseModel):
    value: str
    raw_text: str = ""
    position: Position = "UNKNOWN"
    label: str = ""
    reason: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class SelectedCandidate(BaseModel):
    position: Position = "UNKNOWN"
    label: str = ""
    raw_text: str = ""
    reason: str = ""


class FieldExtraction(BaseModel):
    value: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    selected_candidate: SelectedCandidate | None = None
    candidates: list[Candidate] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    ocr_text: str = ""
    fields: dict[str, FieldExtraction] = Field(default_factory=dict)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    notes: str = ""


@runtime_checkable
class ExtractionProvider(Protocol):
    def extract(self, pdf_bytes: bytes) -> ExtractionResult: ...