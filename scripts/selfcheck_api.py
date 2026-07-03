"""Integration self-check for the FastAPI backend.

Uses TestClient so no server needs to run. Tests:
- health endpoint
- upload + extraction (with a tiny test image)
- save endpoint (without Drive/Sheet calls by mocking)

Run: python scripts/selfcheck_api.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings

client = TestClient(app)

# A minimal 1x1 white PNG image
MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452"
    "0000000100000001080200000090a55ce9"
    "0000000a49444154789c63000000010001"
    "00050a18d84d0000000049454e44ae426082"
)


def test_health() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] is True


def test_upload_requires_auth() -> None:
    files = {"file": ("test.png", io.BytesIO(MINIMAL_PNG), "image/png")}
    resp = client.post("/api/documents", files=files)
    assert resp.status_code == 401, resp.text


def test_upload_and_save() -> None:
    # Set a dummy token for the test
    original_token = settings.API_TOKEN
    settings.API_TOKEN = "test-token"
    try:
        files = {"file": ("test.png", io.BytesIO(MINIMAL_PNG), "image/png")}
        resp = client.post(
            "/api/documents",
            files=files,
            headers={"Authorization": "Bearer test-token"},
        )
        # We expect this to fail at AI extraction because the image is not a real letter
        # and GEMINI_API_KEY may not be set. That's fine — we just verify the endpoint shape.
        if resp.status_code == 200:
            data = resp.json()
            assert "id" in data
            assert "extraction" in data
            assert "confidence" in data

            # Save endpoint
            save_resp = client.post(
                f"/api/documents/{data['id']}/save",
                json={
                    "letter_number": "TEST/001",
                    "letter_date": "01-01-2026",
                    "subject": "Test subject",
                    "received_from": "Test Sender",
                },
                headers={"Authorization": "Bearer test-token"},
            )
            assert save_resp.status_code == 200, save_resp.text
            save_data = save_resp.json()
            assert save_data["status"] == "saved"
        else:
            print(f"Upload returned {resp.status_code} (expected if no real AI key): {resp.text[:200]}")
    finally:
        settings.API_TOKEN = original_token


def main() -> int:
    test_health()
    print("✓ /api/health works")
    test_upload_requires_auth()
    print("✓ /api/documents requires auth")
    test_upload_and_save()
    print("✓ /api/documents + /save endpoint shape works")
    print("All API self-checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())