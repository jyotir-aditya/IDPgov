"""SQLite connection, schema init, FTS5 triggers.

Single user, no contention — raw sqlite3, no ORM.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import settings

DB_PATH = Path("data/letters.db")
TMP_DIR = Path("data/tmp")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft | saved | failed
    letter_number TEXT,
    letter_date TEXT,
    subject TEXT,
    sender_name TEXT,
    sender_designation TEXT,
    department TEXT,
    document_type TEXT,
    summary TEXT,
    keywords TEXT,           -- JSON array
    extraction_json TEXT,    -- full raw AI output incl. candidates+confidence
    ocr_text TEXT,
    confidence REAL,
    drive_file_id TEXT,
    drive_url TEXT,
    local_pdf_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_sheet_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    row_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- FTS5 over searchable fields (unicode61 handles Devanagari)
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    letter_number, subject, sender_name, department, keywords, ocr_text,
    content='documents', content_rowid='rowid',
    tokenize='unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, letter_number, subject, sender_name, department, keywords, ocr_text)
    VALUES (new.rowid, new.letter_number, new.subject, new.sender_name, new.department, new.keywords, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, letter_number, subject, sender_name, department, keywords, ocr_text)
    VALUES ('delete', old.rowid, old.letter_number, old.subject, old.sender_name, old.department, old.keywords, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, letter_number, subject, sender_name, department, keywords, ocr_text)
    VALUES ('delete', old.rowid, old.letter_number, old.subject, old.sender_name, old.department, old.keywords, old.ocr_text);
    INSERT INTO documents_fts(rowid, letter_number, subject, sender_name, department, keywords, ocr_text)
    VALUES (new.rowid, new.letter_number, new.subject, new.sender_name, new.department, new.keywords, new.ocr_text);
END;
"""


def get_db() -> sqlite3.Connection:
    """Returns a sqlite3 connection. Used as FastAPI dependency."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create data dirs + schema. Called on app startup."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()