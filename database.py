import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import lancedb

DB_DIR = Path.home() / ".briefbridge"
DB_DIR.mkdir(exist_ok=True)

SQLITE_PATH = DB_DIR / "briefbridge.db"
LANCE_PATH = DB_DIR / "lancedb"

_conn = None
_lance_db = None


def get_sqlite_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(SQLITE_PATH)
        _conn.row_factory = sqlite3.Row
        _init_sqlite_schema()
    return _conn


def _init_sqlite_schema():
    conn = get_sqlite_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            duration_seconds INTEGER,
            created_at TEXT NOT NULL,
            transcript TEXT,
            summary TEXT,
            notion_page_id TEXT,
            gemini_summary TEXT
        );

        CREATE TABLE IF NOT EXISTS integrations (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            notion_enabled INTEGER DEFAULT 0,
            notion_api_key TEXT,
            gemini_enabled INTEGER DEFAULT 0,
            gemini_api_key TEXT,
            whisper_mode TEXT DEFAULT 'local',
            whisper_api_key TEXT,
            updated_at TEXT NOT NULL
        );

        INSERT OR IGNORE INTO integrations (id, updated_at) VALUES (1, datetime('now'));

        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            recording_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (recording_id) REFERENCES recordings(id)
        );
    """)


def get_lance_db():
    global _lance_db
    if _lance_db is None:
        _lance_db = lancedb.connect(str(LANCE_PATH))
    return _lance_db


def init_lance_schema():
    db = get_lance_db()
    table_names = db.table_names()

    if "transcript_chunks" not in table_names:
        db.create_table(
            "transcript_chunks",
            schema=[
                ("id", "int"),
                ("recording_id", "int"),
                ("chunk_text", "string"),
                ("embedding", "vector(384)"),
                ("created_at", "string"),
            ],
        )


def save_recording(filename: str, filepath: str, duration_seconds: int = 0) -> int:
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO recordings (filename, filepath, duration_seconds, created_at) VALUES (?, ?, ?, ?)",
        (filename, filepath, duration_seconds, datetime.now().isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def update_recording(recording_id: int, **kwargs):
    conn = get_sqlite_connection()
    fields = []
    values = []
    for key, value in kwargs.items():
        fields.append(f"{key} = ?")
        values.append(value)
    if fields:
        values.append(recording_id)
        conn.execute(f"UPDATE recordings SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()


def get_recordings(limit: int = 50) -> List[Dict]:
    conn = get_sqlite_connection()
    rows = conn.execute(
        "SELECT * FROM recordings ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


def get_recording(recording_id: int) -> Optional[Dict]:
    conn = get_sqlite_connection()
    row = conn.execute(
        "SELECT * FROM recordings WHERE id = ?", (recording_id,)
    ).fetchone()
    return dict(row) if row else None


def save_chat_message(role: str, content: str, recording_id: Optional[int] = None):
    conn = get_sqlite_connection()
    conn.execute(
        "INSERT INTO chat_history (role, content, recording_id, created_at) VALUES (?, ?, ?, ?)",
        (role, content, recording_id, datetime.now().isoformat()),
    )
    conn.commit()


def get_chat_history(limit: int = 100) -> List[Dict]:
    conn = get_sqlite_connection()
    rows = conn.execute(
        "SELECT * FROM chat_history ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


def save_chat_message_db(role: str, content: str, recording_id: Optional[int] = None):
    """Alias for save_chat_message for clarity."""
    return save_chat_message(role, content, recording_id)


def get_integrations() -> Dict:
    conn = get_sqlite_connection()
    row = conn.execute("SELECT * FROM integrations WHERE id = 1").fetchone()
    return dict(row) if row else {}


def save_integrations(
    notion_enabled: bool = False,
    notion_api_key: str = "",
    gemini_enabled: bool = False,
    gemini_api_key: str = "",
    whisper_mode: str = "local",
    whisper_api_key: str = "",
):
    conn = get_sqlite_connection()
    conn.execute(
        """UPDATE integrations SET 
           notion_enabled = ?, notion_api_key = ?,
           gemini_enabled = ?, gemini_api_key = ?,
           whisper_mode = ?, whisper_api_key = ?,
           updated_at = ?
           WHERE id = 1""",
        (
            int(notion_enabled),
            notion_api_key,
            int(gemini_enabled),
            gemini_api_key,
            whisper_mode,
            whisper_api_key,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()


def add_transcript_chunk(recording_id: int, chunk_text: str, embedding: List[float]):
    db = get_lance_db()
    table = db.open_table("transcript_chunks")
    table.add(
        [
            {
                "recording_id": recording_id,
                "chunk_text": chunk_text,
                "embedding": embedding,
                "created_at": datetime.now().isoformat(),
            }
        ]
    )


def search_transcripts(query_embedding: List[float], top_k: int = 5) -> List[Dict]:
    db = get_lance_db()
    table = db.open_table("transcript_chunks")
    results = table.search(query_embedding).limit(top_k).to_list()
    return results


def init_databases():
    get_sqlite_connection()
    get_lance_db()
    init_lance_schema()
