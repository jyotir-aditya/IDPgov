"""Gemini extraction provider.

Single multimodal call: file bytes (PDF/JPEG/PNG) + prompt → structured JSON via response_schema.
One retry on timeout/5xx.
"""
from __future__ import annotations

import time

from app.config import settings
from app.services.extraction.base import (
    Candidate,
    ExtractionResult,
    FieldExtraction,
    SelectedCandidate,
)
from app.services.extraction.prompt import PROMPT_TEXT, RESPONSE_SCHEMA

MODEL = "gemini-3.1-flash-lite"


def _detect_mime(data: bytes) -> str:
    """Detect MIME type from magic bytes. Supports PDF, JPEG, PNG."""
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    # Default: assume PDF (the app always sends PDF in production)
    return "application/pdf"


class GeminiProvider:
    """Implements ExtractionProvider via google-genai SDK."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or settings.GEMINI_API_KEY

    def _client(self):
        from google import genai
        return genai.Client(api_key=self._api_key)

    def extract(self, file_bytes: bytes) -> ExtractionResult:
        from google.genai import types

        client = self._client()
        mime_type = _detect_mime(file_bytes)

        def _call():
            return client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                    PROMPT_TEXT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                    temperature=0.1,
                ),
            )

        # One retry on timeout/5xx
        try:
            response = _call()
        except Exception:
            time.sleep(2)
            response = _call()

        return self._parse(response)

    def _parse(self, response) -> ExtractionResult:
        import json

        text = response.text
        data = json.loads(text)

        fields = {}
        raw_fields = data.get("fields", {})
        for name, fdata in raw_fields.items():
            candidates = [
                Candidate(
                    value=c.get("value", ""),
                    raw_text=c.get("raw_text", ""),
                    position=c.get("position") or "UNKNOWN",
                    label=c.get("label", ""),
                    reason=c.get("reason", ""),
                    confidence=c.get("confidence", 0.0),
                )
                for c in fdata.get("candidates", [])
            ]
            selected = fdata.get("selected_candidate")
            fields[name] = FieldExtraction(
                value=fdata.get("value", ""),
                confidence=fdata.get("confidence", 0.0),
                selected_candidate=SelectedCandidate(
                    position=selected.get("position") or "UNKNOWN",
                    label=selected.get("label", ""),
                    raw_text=selected.get("raw_text", ""),
                    reason=selected.get("reason", ""),
                ) if selected else None,
                candidates=candidates,
            )

        return ExtractionResult(
            ocr_text=data.get("ocr_text", ""),
            fields=fields,
            overall_confidence=data.get("overall_confidence", 0.0),
            notes=data.get("notes", ""),
        )