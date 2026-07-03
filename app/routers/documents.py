"""Documents router — merged upload+process, idempotent save, search.

POST /api/documents        — upload file, AI extracts fields, returns draft
POST /api/documents/{id}/save — Drive upload + Sheet append + SQLite update
GET  /api/documents/{id}   — get one document
GET  /api/documents        — list documents (recent, by status)
PUT  /api/documents/{id}   — edit after save (SQLite only)
GET  /api/search           — FTS5 search + date range
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from googleapiclient.errors import HttpError

from app.auth import verify_token
from app.db import TMP_DIR, get_db
from app.models import (
    DocumentOut,
    ExtractionOut,
    FieldExtractionOut,
    HealthResponse,
    SaveFields,
    SaveResponse,
    SearchResponse,
    UploadResponse,
)
from app.services.extraction.factory import get_provider

router = APIRouter(prefix="/api", tags=["documents"])
logger = logging.getLogger("documents")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_doc(row, include_extraction: bool = False) -> DocumentOut:
    keywords = json.loads(row["keywords"]) if row["keywords"] else []
    doc = DocumentOut(
        id=row["id"],
        status=row["status"],
        letter_number=row["letter_number"],
        letter_date=row["letter_date"],
        subject=row["subject"],
        sender_name=row["sender_name"],
        sender_designation=row["sender_designation"],
        department=row["department"],
        document_type=row["document_type"],
        summary=row["summary"],
        keywords=keywords,
        ocr_text=row["ocr_text"],
        confidence=row["confidence"],
        drive_url=row["drive_url"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    if include_extraction and row["extraction_json"]:
        raw = json.loads(row["extraction_json"])
        fields = {}
        for name, fdata in raw.get("fields", {}).items():
            fields[name] = FieldExtractionOut(
                value=fdata.get("value", ""),
                confidence=fdata.get("confidence", 0.0),
                selected_candidate=fdata.get("selected_candidate"),
                candidates=fdata.get("candidates", []),
            )
        doc.extraction = ExtractionOut(
            ocr_text=raw.get("ocr_text", ""),
            fields=fields,
            overall_confidence=raw.get("overall_confidence", 0.0),
            notes=raw.get("notes", ""),
        )
    return doc


@router.get("/health", response_model=HealthResponse)
async def health():
    from app.db import DB_PATH
    return HealthResponse(status="ok", db=DB_PATH.exists())


@router.post("/documents", response_model=UploadResponse)
async def upload_and_process(
    file: UploadFile = File(...),
    _token: str = Depends(verify_token),
):
    """Upload a file (PDF/JPEG/PNG), run AI extraction, return draft."""
    # Validate file type
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Detect type from magic bytes
    from app.services.extraction.gemini import _detect_mime
    mime = _detect_mime(content)
    if mime not in ("application/pdf", "image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Only PDF, JPEG, PNG accepted")

    # Save to temp
    doc_id = str(uuid.uuid4())
    ext = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}[mime]
    tmp_path = TMP_DIR / f"{doc_id}{ext}"
    tmp_path.write_bytes(content)

    # Run extraction
    try:
        provider = get_provider()
        result = provider.extract(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    # Store raw extraction JSON
    extraction_dict = result.model_dump()
    extraction_json = json.dumps(extraction_dict, ensure_ascii=False)

    # Extract individual fields for SQLite columns
    fields = result.fields
    letter_number = fields.get("letter_number", None)
    letter_date = fields.get("letter_date", None)
    subject = fields.get("subject", None)
    received_from = fields.get("received_from", None)

    # Insert draft row
    db = get_db()
    now = _now()
    db.execute(
        """INSERT INTO documents
           (id, status, letter_number, letter_date, subject, sender_name,
            sender_designation, extraction_json, ocr_text, confidence,
            local_pdf_path, created_at, updated_at)
           VALUES (?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            doc_id,
            letter_number.value if letter_number else "",
            letter_date.value if letter_date else "",
            subject.value if subject else "",
            received_from.value if received_from else "",
            "",  # sender_designation — could parse from received_from later
            extraction_json,
            result.ocr_text,
            result.overall_confidence,
            str(tmp_path),
            now, now,
        ),
    )
    db.commit()
    db.close()

    # Build response
    fields_out = {}
    for name, f in fields.items():
        fields_out[name] = FieldExtractionOut(
            value=f.value, confidence=f.confidence,
            selected_candidate=f.selected_candidate.model_dump() if f.selected_candidate else None,
            candidates=[c.model_dump() for c in f.candidates],
        )

    return UploadResponse(
        id=doc_id,
        extraction=ExtractionOut(
            ocr_text=result.ocr_text,
            fields=fields_out,
            overall_confidence=result.overall_confidence,
            notes=result.notes,
        ),
        confidence=result.overall_confidence,
    )


@router.post("/documents/{doc_id}/save", response_model=SaveResponse)
async def save_document(
    doc_id: str,
    fields: SaveFields,
    _token: str = Depends(verify_token),
):
    """Save reviewed fields: Drive upload + Sheet append + SQLite update.

    Idempotent: skips Drive upload if drive_file_id already set.
    Sheet append failure never fails the save — enqueues to pending_sheet_rows.
    """
    db = get_db()
    row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Document not found")

    now = _now()
    drive_file_id = row["drive_file_id"]
    drive_url = row["drive_url"]
    local_path = row["local_pdf_path"]

    # Drive upload (skip if already done)
    if not drive_file_id and local_path and Path(local_path).exists():
        try:
            # Filename: {letter_no}_{date}_{id}.pdf
            safe_no = fields.letter_number.replace("/", "-").replace("\\", "-") or "unknown"
            filename = f"{safe_no}_{fields.letter_date}_{doc_id[:8]}.pdf"
            from app.services.drive import upload_pdf
            drive_file_id, drive_url = upload_pdf(local_path, filename)
        except Exception:
            # Drive failure doesn't block save — user can retry
            logger.exception("Drive upload failed for document %s", doc_id)
            drive_url = None

    # Sheet append
    sheet_appended = False
    sl_no = None
    try:
        from app.services.sheets import append_register_row
        sl_no = append_register_row(
            received_from=fields.received_from or fields.sender_name,
            letter_no=fields.letter_number,
            letter_date=fields.letter_date,
            subject=fields.subject,
        )
        sheet_appended = True
    except Exception:
        logger.exception("Sheet append failed for document %s, enqueueing for retry", doc_id)
        # Enqueue for retry
        row_json = json.dumps({
            "received_from": fields.received_from or fields.sender_name,
            "letter_no": fields.letter_number,
            "letter_date": fields.letter_date,
            "subject": fields.subject,
        }, ensure_ascii=False)
        db.execute(
            "INSERT INTO pending_sheet_rows (document_id, row_json, created_at) VALUES (?, ?, ?)",
            (doc_id, row_json, now),
        )

    # Update SQLite
    keywords_json = json.dumps(fields.keywords, ensure_ascii=False) if fields.keywords else None
    db.execute(
        """UPDATE documents SET
           status = 'saved', letter_number = ?, letter_date = ?, subject = ?,
           sender_name = ?, sender_designation = ?, department = ?,
           document_type = ?, summary = ?, keywords = ?,
           drive_file_id = ?, drive_url = ?, updated_at = ?
           WHERE id = ?""",
        (
            fields.letter_number, fields.letter_date, fields.subject,
            fields.sender_name, fields.sender_designation, fields.department,
            fields.document_type, fields.summary, keywords_json,
            drive_file_id, drive_url, now, doc_id,
        ),
    )
    db.commit()

    # Clean up temp PDF on success
    if local_path and Path(local_path).exists():
        try:
            Path(local_path).unlink()
        except OSError:
            pass

    db.close()

    return SaveResponse(
        id=doc_id, status="saved", drive_url=drive_url,
        sheet_appended=sheet_appended, sl_no=sl_no,
    )


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: str, _token: str = Depends(verify_token)):
    db = get_db()
    row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return _row_to_doc(row, include_extraction=True)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    _token: str = Depends(verify_token),
):
    db = get_db()
    if status:
        rows = db.execute(
            "SELECT * FROM documents WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    db.close()
    return [_row_to_doc(r) for r in rows]


@router.put("/documents/{doc_id}", response_model=DocumentOut)
async def update_document(
    doc_id: str,
    fields: SaveFields,
    _token: str = Depends(verify_token),
):
    """Edit after save — SQLite only. Sheet drift accepted (see Cut list)."""
    db = get_db()
    row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Document not found")

    now = _now()
    keywords_json = json.dumps(fields.keywords, ensure_ascii=False) if fields.keywords else None
    db.execute(
        """UPDATE documents SET
           letter_number = ?, letter_date = ?, subject = ?,
           sender_name = ?, sender_designation = ?, department = ?,
           document_type = ?, summary = ?, keywords = ?, updated_at = ?
           WHERE id = ?""",
        (
            fields.letter_number, fields.letter_date, fields.subject,
            fields.sender_name, fields.sender_designation, fields.department,
            fields.document_type, fields.summary, keywords_json, now, doc_id,
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    db.close()
    return _row_to_doc(row)


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, le=100),
    _token: str = Depends(verify_token),
):
    """FTS5 search across letter_number, subject, sender, department, keywords, ocr_text."""
    db = get_db()
    # FTS5 match with snippet
    rows = db.execute(
        """SELECT d.* FROM documents_fts f
           JOIN documents d ON d.rowid = f.rowid
           WHERE documents_fts MATCH ?
           ORDER BY rank
           LIMIT ?""",
        (q, limit),
    ).fetchall()
    db.close()
    results = [_row_to_doc(r) for r in rows]
    return SearchResponse(results=results, total=len(results))