"""Google Drive service — PDF upload to Year/Month folders.

Folder IDs are cached in memory to avoid repeated API calls.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_folder_cache: dict[str, str] = {}  # "2026/June" -> folder_id


def _creds():
    from google.oauth2 import service_account
    sa_path = Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    if not sa_path.exists():
        raise FileNotFoundError(f"Service account file not found: {sa_path}")
    return service_account.Credentials.from_service_account_file(str(sa_path), scopes=SCOPES)


def _service():
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    return build("drive", "v3", credentials=_creds(), cache_discovery=False)


def _get_or_create_folder(svc, name: str, parent_id: str) -> str:
    """Find a folder by name under parent, or create it."""
    # Check cache first
    cache_key = f"{parent_id}/{name}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]

    # Search for existing folder
    resp = svc.files().list(
        q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false",
        spaces="drive", fields="files(id, name)", pageSize=1,
    ).execute()
    files = resp.get("files", [])
    if files:
        folder_id = files[0]["id"]
    else:
        # Create it
        folder = svc.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
            fields="id",
        ).execute()
        folder_id = folder["id"]

    _folder_cache[cache_key] = folder_id
    return folder_id


def _get_year_month_folder(svc) -> str:
    """Get or create Year/Month folder structure under the root folder."""
    now = datetime.now()
    year = str(now.year)
    month = now.strftime("%B")  # June, July, etc.

    year_id = _get_or_create_folder(svc, year, settings.DRIVE_FOLDER_ID)
    month_id = _get_or_create_folder(svc, month, year_id)
    return month_id


def upload_pdf(local_path: str, filename: str) -> tuple[str, str]:
    """Upload a PDF to Drive Year/Month folder. Returns (file_id, web_view_url)."""
    from googleapiclient.http import MediaFileUpload

    svc = _service()
    folder_id = _get_year_month_folder(svc)

    media = MediaFileUpload(local_path, mimetype="application/pdf", resumable=True)
    file = svc.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    file_id = file["id"]
    url = file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
    return file_id, url