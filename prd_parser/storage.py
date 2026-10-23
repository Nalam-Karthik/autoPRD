"""SQLite persistence for parsed PRD documents.

Every successful PRD parse (file upload or raw text) is written to a local
SQLite database so the extracted response can be inspected later, independently
of the request that produced it.

Configuration:
    AUTOPRD_DB_PATH  Path to the SQLite file.
                     Defaults to ``data/autoprd.db`` relative to the cwd.

Public helpers:
    init_db, save_document, list_documents, get_document, delete_document,
    clear_documents, count_documents, database_path
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = Path("data") / "autoprd.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    source_type TEXT NOT NULL DEFAULT 'upload',
    source_format TEXT NOT NULL DEFAULT 'markdown',
    requirement_id TEXT,
    functional_specification TEXT,
    acceptance_criteria TEXT NOT NULL DEFAULT '[]',
    edge_case_assumptions TEXT NOT NULL DEFAULT '[]',
    extraction_method TEXT NOT NULL DEFAULT 'heuristic',
    word_count INTEGER NOT NULL DEFAULT 0,
    page_count INTEGER,
    content_hash TEXT,
    prd_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_created_at
    ON documents (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_requirement_id
    ON documents (requirement_id);
"""


def database_path() -> Path:
    """Return the configured database path (re-read on every call)."""
    configured = os.getenv("AUTOPRD_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    """Open a connection, creating the parent directory and schema if needed."""
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def init_db() -> Path:
    """Create the database file and schema if they do not exist."""
    with closing(_connect()):
        pass
    return database_path()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row_to_record(row: sqlite3.Row, *, include_text: bool = False) -> Dict[str, Any]:
    """Convert a DB row into the public record shape."""
    criteria = json.loads(row["acceptance_criteria"] or "[]")
    assumptions = json.loads(row["edge_case_assumptions"] or "[]")

    record: Dict[str, Any] = {
        "id": row["id"],
        "filename": row["filename"],
        "source_type": row["source_type"],
        "source_format": row["source_format"],
        "requirement_id": row["requirement_id"],
        "functional_specification": row["functional_specification"],
        "acceptance_criteria": criteria,
        "edge_case_assumptions": assumptions,
        "extraction_method": row["extraction_method"],
        "word_count": row["word_count"],
        "page_count": row["page_count"],
        "content_hash": row["content_hash"],
        "created_at": row["created_at"],
    }

    # The response mirrors the shape returned by /upload-file and /parse-prd,
    # so the stored row can be displayed exactly like the live API response.
    record["response"] = {
        "requirement_id": row["requirement_id"],
        "functional_specification": row["functional_specification"],
        "acceptance_criteria": criteria,
        "edge_case_assumptions": assumptions,
        "source_format": row["source_format"],
        "extraction_method": row["extraction_method"],
        "filename": row["filename"],
        "word_count": row["word_count"],
        "document_id": row["id"],
    }

    if include_text:
        record["prd_text"] = row["prd_text"]

    return record


def save_document(
    *,
    filename: Optional[str],
    source_format: str,
    requirement_id: str,
    functional_specification: str,
    acceptance_criteria: List[str],
    edge_case_assumptions: List[Dict[str, str]],
    extraction_method: str = "heuristic",
    word_count: int = 0,
    page_count: Optional[int] = None,
    prd_text: str = "",
    source_type: str = "upload",
) -> Dict[str, Any]:
    """Insert a parsed document and return the stored record."""
    created_at = _utc_now()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            """
            INSERT INTO documents (
                filename, source_type, source_format, requirement_id,
                functional_specification, acceptance_criteria,
                edge_case_assumptions, extraction_method, word_count,
                page_count, content_hash, prd_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filename,
                source_type,
                source_format,
                requirement_id,
                functional_specification,
                json.dumps(acceptance_criteria, ensure_ascii=False),
                json.dumps(edge_case_assumptions, ensure_ascii=False),
                extraction_method,
                int(word_count or 0),
                page_count,
                _content_hash(prd_text or ""),
                prd_text or "",
                created_at,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()

    return _row_to_record(row)


def list_documents(
    *,
    limit: int = 50,
    offset: int = 0,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return stored documents, newest first (without the full PRD text)."""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    sql = "SELECT * FROM documents"
    params: List[Any] = []

    if query:
        sql += (
            " WHERE COALESCE(filename, '') LIKE ?"
            " OR COALESCE(requirement_id, '') LIKE ?"
            " OR COALESCE(functional_specification, '') LIKE ?"
        )
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])

    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with closing(_connect()) as conn:
        rows = conn.execute(sql, params).fetchall()

    return [_row_to_record(row) for row in rows]


def count_documents(query: Optional[str] = None) -> int:
    """Return the number of stored documents, optionally filtered."""
    sql = "SELECT COUNT(*) AS total FROM documents"
    params: List[Any] = []

    if query:
        sql += (
            " WHERE COALESCE(filename, '') LIKE ?"
            " OR COALESCE(requirement_id, '') LIKE ?"
            " OR COALESCE(functional_specification, '') LIKE ?"
        )
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])

    with closing(_connect()) as conn:
        row = conn.execute(sql, params).fetchone()

    return int(row["total"] if row else 0)


def get_document(document_id: int) -> Optional[Dict[str, Any]]:
    """Return a single stored document including its full PRD text."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (int(document_id),)
        ).fetchone()

    if row is None:
        return None
    return _row_to_record(row, include_text=True)


def delete_document(document_id: int) -> bool:
    """Delete one stored document. Returns True when a row was removed."""
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "DELETE FROM documents WHERE id = ?", (int(document_id),)
        )
        conn.commit()
        return cursor.rowcount > 0


def clear_documents() -> int:
    """Delete every stored document. Returns the number of rows removed."""
    with closing(_connect()) as conn:
        cursor = conn.execute("DELETE FROM documents")
        conn.commit()
        return cursor.rowcount
