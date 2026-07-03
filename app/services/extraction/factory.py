"""Provider factory — selects extraction provider by AI_PROVIDER env var.

Add a new provider: create a new file implementing ExtractionProvider,
then add one elif here.
"""
from __future__ import annotations

from app.config import settings
from app.services.extraction.base import ExtractionProvider


def get_provider() -> ExtractionProvider:
    provider = settings.AI_PROVIDER.lower()
    if provider == "gemini":
        from app.services.extraction.gemini import GeminiProvider
        return GeminiProvider()
    raise ValueError(f"Unknown AI_PROVIDER: {settings.AI_PROVIDER}")