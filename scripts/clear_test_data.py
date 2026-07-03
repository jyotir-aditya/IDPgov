"""One-off terminal script to wipe test data before going live.

Deliberately NOT an API endpoint or app feature — see conversation history:
this is a records register, so destructive wipes should be a deliberate,
manual, terminal-only action, never something an app button or a bug could
trigger by accident.

Clears:
  - All rows in the SQLite `documents` and `pending_sheet_rows` tables (FTS
    index is kept in sync automatically via the existing triggers)
  - Local temp scan files under data/tmp/
  - All objects in the R2 bucket

Deliberately does NOT touch the Google Sheet register — delete test rows
there by hand in the Sheets UI so you keep control over the header row and
the SL No. sequence.

Usage:
    python scripts/clear_test_data.py            # dry run, shows what would be deleted
    python scripts/clear_test_data.py --confirm   # actually deletes
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DB_PATH, TMP_DIR, get_db  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> None:
    confirm = "--confirm" in sys.argv

    db = get_db()
    docs = db.execute("SELECT id, local_pdf_path FROM documents").fetchall()
    pending = db.execute("SELECT id FROM pending_sheet_rows").fetchall()

    print(f"SQLite ({DB_PATH}):")
    print(f"  {len(docs)} document row(s)")
    print(f"  {len(pending)} pending_sheet_rows row(s)")

    local_files = [d["local_pdf_path"] for d in docs if d["local_pdf_path"]]
    tmp_files = list(TMP_DIR.glob("*")) if TMP_DIR.exists() else []
    print(f"Local temp files: {len(tmp_files)} file(s) in {TMP_DIR}/")

    r2_keys: list[str] = []
    r2_error = None
    if settings.R2_BUCKET_NAME:
        try:
            from app.services.r2 import _client
            client = _client()
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=settings.R2_BUCKET_NAME):
                r2_keys.extend(obj["Key"] for obj in page.get("Contents", []))
            print(f"R2 bucket '{settings.R2_BUCKET_NAME}': {len(r2_keys)} object(s)")
        except Exception as e:
            r2_error = e
            print(f"R2 bucket '{settings.R2_BUCKET_NAME}': could not list objects ({e})")
    else:
        print("R2 bucket: not configured, skipping")

    if not confirm:
        print("\nDry run — nothing deleted. Re-run with --confirm to actually delete.")
        db.close()
        return

    # SQLite
    db.execute("DELETE FROM documents")
    db.execute("DELETE FROM pending_sheet_rows")
    db.commit()
    db.close()
    print(f"\nDeleted {len(docs)} document row(s) and {len(pending)} pending_sheet_rows row(s).")

    # Local temp files (covers both DB-referenced paths and any orphans in data/tmp/)
    deleted_files = 0
    for f in tmp_files:
        try:
            f.unlink()
            deleted_files += 1
        except OSError:
            pass
    print(f"Deleted {deleted_files} local temp file(s).")

    # R2 objects
    if r2_keys and r2_error is None:
        from app.services.r2 import _client
        client = _client()
        # delete_objects takes max 1000 keys per call
        for i in range(0, len(r2_keys), 1000):
            batch = r2_keys[i : i + 1000]
            client.delete_objects(
                Bucket=settings.R2_BUCKET_NAME,
                Delete={"Objects": [{"Key": k} for k in batch]},
            )
        print(f"Deleted {len(r2_keys)} R2 object(s).")

    print("\nDone. Remember: the Google Sheet register was NOT touched — clear test rows there by hand.")


if __name__ == "__main__":
    main()
