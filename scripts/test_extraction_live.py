"""Live test: send a real file to Gemini and print the extraction result.

Usage: python scripts/test_extraction_live.py <path-to-file>

Supports PDF, JPEG, PNG (MIME auto-detected from magic bytes).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.extraction.factory import get_provider


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_extraction_live.py <path-to-file>")
        return 1

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"File not found: {file_path}")
        return 1

    file_bytes = file_path.read_bytes()
    print(f"Sending {len(file_bytes)} bytes to Gemini...")

    provider = get_provider()
    result = provider.extract(file_bytes)

    print("\n" + "=" * 60)
    print(f"Overall confidence: {result.overall_confidence}")
    print(f"Notes: {result.notes}")
    print("=" * 60)

    for name, field in result.fields.items():
        print(f"\n--- {name} ---")
        print(f"  value:     {field.value}")
        print(f"  confidence: {field.confidence}")
        if field.selected_candidate:
            s = field.selected_candidate
            print(f"  selected:  [{s.position}] label={s.label!r} raw={s.raw_text!r} -- {s.reason}")
        if field.candidates:
            print(f"  candidates ({len(field.candidates)}):")
            for c in field.candidates:
                print(f"    - {c.value} [{c.position}] label={c.label!r} raw={c.raw_text!r} conf={c.confidence} -- {c.reason}")

    print(f"\n--- OCR text (first 500 chars) ---")
    print(result.ocr_text[:500])
    if len(result.ocr_text) > 500:
        print(f"... ({len(result.ocr_text)} total chars)")

    return 0


if __name__ == "__main__":
    sys.exit(main())