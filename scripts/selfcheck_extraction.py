"""Self-check for the extraction parsing logic.

Tests GeminiProvider._parse with a mock Gemini response.
No API key or PDF needed.

Run: python scripts/selfcheck_extraction.py
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.extraction.gemini import GeminiProvider


MOCK_JSON = {
    "ocr_text": "विषय: ग्रीष्मकाल में राज्य में पड़ने वाली भीषण गर्मी...",
    "fields": {
        "letter_number": {
            "value": "1061",
            "confidence": 0.9,
            "selected_candidate": {
                "position": "BOTTOM_CENTER",
                "label": "पत्रांक",
                "raw_text": "पत्रांक- 1061",
                "reason": "निचले हिस्से में हस्तलिखित पत्रांक",
            },
            "candidates": [
                {"value": "68/2024", "reason": "हेडर में संदर्भ संख्या",
                 "position": "BODY", "label": "", "raw_text": "पत्र संख्या 68/2024", "confidence": 0.2},
                {"value": "1061", "reason": "निचले हिस्से में हस्तलिखित पत्रांक",
                 "position": "BOTTOM_CENTER", "label": "पत्रांक", "raw_text": "पत्रांक- 1061", "confidence": 0.8},
            ],
        },
        "letter_date": {
            "value": "23-06-2026",
            "confidence": 0.85,
            "candidates": [
                {"value": "23-06-2026", "reason": "पत्रांक के बगल में हस्तलिखित तिथि"}
            ],
        },
        "subject": {
            "value": "ग्रीष्मकाल में स्कूल संचालन समय परिवर्तन",
            "confidence": 0.95,
            "candidates": [],
        },
        "received_from": {
            "value": "सज्जन आर०, निदेशक (माध्यमिक शिक्षा)",
            "confidence": 0.8,
            "candidates": [],
        },
    },
    "overall_confidence": 0.875,
    "notes": "पत्रांक हस्तलिखित है, तिथि के बगल में।",
}


def main() -> int:
    provider = GeminiProvider(api_key="dummy")

    # Mock response object with .text attribute
    mock_response = SimpleNamespace(text=json.dumps(MOCK_JSON))
    result = provider._parse(mock_response)

    # OCR text preserved
    assert result.ocr_text == MOCK_JSON["ocr_text"], "ocr_text mismatch"

    # Fields parsed correctly
    assert "letter_number" in result.fields, "letter_number missing"
    assert result.fields["letter_number"].value == "1061"
    assert result.fields["letter_number"].confidence == 0.9
    assert len(result.fields["letter_number"].candidates) == 2
    assert result.fields["letter_number"].candidates[0].value == "68/2024"
    assert result.fields["letter_number"].candidates[0].reason == "हेडर में संदर्भ संख्या"

    # New rich candidate metadata
    assert result.fields["letter_number"].candidates[0].position == "BODY"
    assert result.fields["letter_number"].candidates[1].position == "BOTTOM_CENTER"
    assert result.fields["letter_number"].candidates[1].label == "पत्रांक"
    assert result.fields["letter_number"].candidates[1].raw_text == "पत्रांक- 1061"
    assert result.fields["letter_number"].candidates[1].confidence == 0.8
    sel = result.fields["letter_number"].selected_candidate
    assert sel is not None and sel.position == "BOTTOM_CENTER" and sel.label == "पत्रांक"

    # Old-shape candidates (no position/selected_candidate) still parse with defaults
    assert result.fields["letter_date"].candidates[0].position == "UNKNOWN"
    assert result.fields["letter_date"].selected_candidate is None

    assert result.fields["letter_date"].value == "23-06-2026"
    assert result.fields["subject"].value == "ग्रीष्मकाल में स्कूल संचालन समय परिवर्तन"
    assert result.fields["received_from"].value == "सज्जन आर०, निदेशक (माध्यमिक शिक्षा)"

    # Overall confidence
    assert result.overall_confidence == 0.875

    # Notes
    assert result.notes == "पत्रांक हस्तलिखित है, तिथि के बगल में।"

    # Empty candidates list preserved
    assert result.fields["subject"].candidates == []

    # MIME detection from magic bytes
    from app.services.extraction.gemini import _detect_mime
    assert _detect_mime(b"%PDF-1.4...") == "application/pdf", "PDF magic bytes"
    assert _detect_mime(b"\xff\xd8\xff\xe0...") == "image/jpeg", "JPEG magic bytes"
    assert _detect_mime(b"\x89PNG\r\n\x1a\n...") == "image/png", "PNG magic bytes"

    print("All extraction parsing checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())