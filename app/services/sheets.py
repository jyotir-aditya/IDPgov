"""Google Sheets register service.

Appends one row per saved letter with these columns:
  SL No. | Date | From whom received | Letter No. | Letter Date | Subject | Disposal | PDF Link

SL No. auto-increments as BEP/UP001, BEP/UP002, ...
Date is the scan/save date (today).
Disposal is left empty for the user to fill in Excel.
PDF Link is the Drive webViewLink for the scanned document (empty if the
Drive upload failed — see documents.py's save flow).
All other fields come from the reviewed extraction.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADER_ROW = ["SL No.", "Date", "From whom received", "Letter No.", "Letter Date", "Subject", "Disposal", "PDF Link"]
# ponytail: 3-digit zero-pad; after 999 it naturally becomes 4 digits — fine for a single office.
SL_NO_RE = re.compile(r"(\d+)$")


def _creds():
    from google.oauth2 import service_account
    sa_path = Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    if not sa_path.exists():
        raise FileNotFoundError(f"Service account file not found: {sa_path}")
    return service_account.Credentials.from_service_account_file(str(sa_path), scopes=SCOPES)


def _service():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=_creds(), cache_discovery=False)


def ensure_header() -> None:
    """Write the header row if the sheet's first row is empty or mismatched."""
    svc = _service()
    resp = svc.spreadsheets().values().get(
        spreadsheetId=settings.SHEET_ID, range="A1:H1"
    ).execute()
    values = resp.get("values", [])
    if values and values[0] == HEADER_ROW:
        return
    svc.spreadsheets().values().update(
        spreadsheetId=settings.SHEET_ID,
        range="A1",
        valueInputOption="RAW",
        body={"values": [HEADER_ROW]},
    ).execute()


def _compute_next_sl_no(existing_cells: list[str]) -> str:
    """Given existing SL No. cells, return the next one. Pure function for testing."""
    max_n = 0
    for cell in existing_cells:
        cell = cell.strip()
        if cell == HEADER_ROW[0]:
            continue
        m = SL_NO_RE.search(cell)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{settings.SL_NO_PREFIX}{max_n + 1:03d}"


def _next_sl_no(svc) -> str:
    """Read column A, find the highest existing SL No., increment by 1."""
    resp = svc.spreadsheets().values().get(
        spreadsheetId=settings.SHEET_ID, range="A:A"
    ).execute()
    values = resp.get("values", [])
    cells = [str(row[0]) if row else "" for row in values]
    return _compute_next_sl_no(cells)


def _as_text(value: str) -> str:
    """Prefix with apostrophe so Google Sheets treats the value as plain text.
    
    Without this, strings like '19-06-2026' are auto-converted to date serials.
    """
    if not value:
        return ""
    return f"'{value}"


def append_register_row(
    *,
    received_from: str = "",
    letter_no: str = "",
    letter_date: str = "",
    subject: str = "",
    scan_date: str | None = None,
    pdf_link: str = "",
) -> str:
    """Append one register row. Returns the generated SL No.

    All fields are the final reviewed values from the extraction review screen.
    scan_date defaults to today (DD-MM-YYYY). pdf_link is the Drive
    webViewLink — left blank if the Drive upload failed or hasn't run.
    """
    ensure_header()
    svc = _service()
    sl_no = _next_sl_no(svc)
    today = scan_date or date.today().strftime("%d-%m-%Y")

    # Dates are forced to text with a leading apostrophe so Sheets doesn't
    # convert them to date serial numbers (e.g. 46192).
    row = [
        sl_no,
        _as_text(today),
        received_from,
        letter_no,
        _as_text(letter_date),
        subject,
        "",
        pdf_link,
    ]

    svc.spreadsheets().values().append(
        spreadsheetId=settings.SHEET_ID,
        range="A:H",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    return sl_no