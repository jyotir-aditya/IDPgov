"""Background retry loop (asyncio task, runs every 60s):
  - flush pending_sheet_rows (Sheet append retries)
  - mark drafts older than 7 days as 'failed' and delete their temp PDFs
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db import get_db

logger = logging.getLogger("retry")

INTERVAL_SECONDS = 60
STALE_DRAFT_DAYS = 7
MAX_ATTEMPTS = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def flush_pending_sheet_rows() -> None:
    from app.services.sheets import append_register_row

    db = get_db()
    rows = db.execute(
        "SELECT * FROM pending_sheet_rows WHERE attempts < ? ORDER BY id", (MAX_ATTEMPTS,)
    ).fetchall()
    for row in rows:
        data = json.loads(row["row_json"])
        try:
            sl_no = append_register_row(
                received_from=data.get("received_from", ""),
                letter_no=data.get("letter_no", ""),
                letter_date=data.get("letter_date", ""),
                subject=data.get("subject", ""),
            )
            db.execute("DELETE FROM pending_sheet_rows WHERE id = ?", (row["id"],))
            db.execute(
                "UPDATE documents SET updated_at = ? WHERE id = ?",
                (_now(), row["document_id"]),
            )
            logger.info("Flushed pending sheet row for document %s (sl_no=%s)", row["document_id"], sl_no)
        except Exception as e:
            db.execute(
                "UPDATE pending_sheet_rows SET attempts = attempts + 1 WHERE id = ?",
                (row["id"],),
            )
            logger.warning("Retry failed for document %s: %s", row["document_id"], e)
    db.commit()
    db.close()


def clean_stale_drafts() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_DRAFT_DAYS)).isoformat()
    db = get_db()
    rows = db.execute(
        "SELECT id, local_pdf_path FROM documents WHERE status = 'draft' AND created_at < ?",
        (cutoff,),
    ).fetchall()
    for row in rows:
        if row["local_pdf_path"]:
            try:
                Path(row["local_pdf_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        db.execute(
            "UPDATE documents SET status = 'failed', updated_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
    if rows:
        db.commit()
        logger.info("Marked %d stale draft(s) as failed", len(rows))
    db.close()


async def retry_loop() -> None:
    """Runs forever until cancelled; call as an asyncio background task from lifespan."""
    while True:
        try:
            flush_pending_sheet_rows()
            clean_stale_drafts()
        except Exception:
            logger.exception("Retry loop iteration failed")
        await asyncio.sleep(INTERVAL_SECONDS)
