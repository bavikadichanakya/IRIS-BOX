import asyncio
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any
import json


class Database:
    """Async SQLite database for persistent conversation logs, latency metrics, and error tracking."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn = None

    async def connect(self):
        """Establish database connection and initialize schema."""
        self._conn = await aiosqlite.connect(self.db_path)
        await self._init_schema()

    async def close(self):
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _init_schema(self):
        """Initialize database schema with tables and indexes."""
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                tool_calls TEXT
            );

            CREATE TABLE IF NOT EXISTS latency_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                llm_time_ms REAL,
                tool_time_ms REAL,
                audio_latency_ms REAL,
                total_time_ms REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                stack_trace TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
            CREATE INDEX IF NOT EXISTS idx_latency_session ON latency_metrics(session_id);
            CREATE INDEX IF NOT EXISTS idx_errors_session ON errors(session_id);
        """)
        await self._conn.commit()

    async def add_conversation(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None
    ) -> int:
        """Insert a conversation message and return the new row ID."""
        cursor = await self._conn.execute(
            "INSERT INTO conversations (session_id, role, content, tool_calls) VALUES (?, ?, ?, ?)",
            (session_id, role, content, json.dumps(tool_calls) if tool_calls else None)
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_conversations(self, session_id: str) -> List[Dict]:
        """Retrieve all conversation messages for a given session, ordered by timestamp."""
        cursor = await self._conn.execute(
            "SELECT id, session_id, role, content, timestamp, tool_calls FROM conversations WHERE session_id = ? ORDER BY timestamp",
            (session_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def add_latency_metric(
        self,
        session_id: str,
        llm_time_ms: float,
        tool_time_ms: float,
        audio_latency_ms: float,
        total_time_ms: float
    ) -> int:
        """Insert a latency metric record and return the new row ID."""
        cursor = await self._conn.execute(
            "INSERT INTO latency_metrics (session_id, llm_time_ms, tool_time_ms, audio_latency_ms, total_time_ms) VALUES (?, ?, ?, ?, ?)",
            (session_id, llm_time_ms, tool_time_ms, audio_latency_ms, total_time_ms)
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_latency_metrics(self, session_id: Optional[str] = None) -> List[Dict]:
        """Retrieve latency metrics, optionally filtered by session_id."""
        if session_id:
            cursor = await self._conn.execute(
                "SELECT * FROM latency_metrics WHERE session_id = ? ORDER BY timestamp",
                (session_id,)
            )
        else:
            cursor = await self._conn.execute("SELECT * FROM latency_metrics ORDER BY timestamp")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def add_error(
        self,
        session_id: Optional[str],
        error_type: str,
        error_message: str,
        stack_trace: Optional[str] = None
    ) -> int:
        """Insert an error record and return the new row ID."""
        cursor = await self._conn.execute(
            "INSERT INTO errors (session_id, error_type, error_message, stack_trace) VALUES (?, ?, ?, ?)",
            (session_id, error_type, error_message, stack_trace)
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_errors(self, session_id: Optional[str] = None) -> List[Dict]:
        """Retrieve error records, optionally filtered by session_id."""
        if session_id:
            cursor = await self._conn.execute(
                "SELECT * FROM errors WHERE session_id = ? ORDER BY timestamp",
                (session_id,)
            )
        else:
            cursor = await self._conn.execute("SELECT * FROM errors ORDER BY timestamp")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
