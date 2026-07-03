"""Pydantic request/response models for the API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FieldExtractionOut(BaseModel):
    value: str = ""
    confidence: float = 0.0
    selected_candidate: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class ExtractionOut(BaseModel):
    ocr_text: str = ""
    fields: dict[str, FieldExtractionOut] = Field(default_factory=dict)
    overall_confidence: float = 0.0
    notes: str = ""


class UploadResponse(BaseModel):
    id: str
    extraction: ExtractionOut
    confidence: float


class SaveFields(BaseModel):
    """Final edited fields from the review screen."""
    letter_number: str = ""
    letter_date: str = ""
    subject: str = ""
    received_from: str = ""  # sender name + designation combined
    sender_name: str = ""
    sender_designation: str = ""
    department: str = ""
    document_type: str = ""
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)


class SaveResponse(BaseModel):
    id: str
    status: str
    drive_url: str | None = None
    sheet_appended: bool = True
    sl_no: str | None = None


class DocumentOut(BaseModel):
    id: str
    status: str
    letter_number: str | None = None
    letter_date: str | None = None
    subject: str | None = None
    sender_name: str | None = None
    sender_designation: str | None = None
    department: str | None = None
    document_type: str | None = None
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    ocr_text: str | None = None
    confidence: float | None = None
    drive_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    extraction: ExtractionOut | None = None


class SearchResponse(BaseModel):
    results: list[DocumentOut]
    total: int


class HealthResponse(BaseModel):
    status: str
    db: bool