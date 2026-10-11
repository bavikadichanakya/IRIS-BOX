import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field

import aiosqlite

logger = logging.getLogger("iris.storage.memory_store")


class PreferenceRecord(BaseModel):
    user_id: str
    key: str
    value: Any
    category: str = "general"
    updated_at: Optional[str] = None


class FactRecord(BaseModel):
    id: int
    user_id: str
    fact: str
    confidence: float
    source_session_id: Optional[str] = None
    confirmed_by_user: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _parse_stored_value(val: Any) -> Any:
    if not isinstance(val, str):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val


def _serialize_value(val: Any) -> str:
    if isinstance(val, str):
        return val
    return json.dumps(val)


class MemoryStore:
    """
    Persistent, local preference and memory store for user personalization.
    Provides strict epistemic separation between explicit preferences and inferred facts.
    """
    def __init__(self, db: Optional[Any] = None, db_path: str = "iris.db"):
        self.db = db
        self.db_path = db_path
        self._local_conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        if self.db and getattr(self.db, "_conn", None):
            return self.db._conn
        if self._local_conn is None:
            self._local_conn = await aiosqlite.connect(self.db_path)
            self._local_conn.row_factory = aiosqlite.Row
            await self._init_schema(self._local_conn)
        return self._local_conn

    async def _init_schema(self, conn: aiosqlite.Connection):
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id TEXT NOT NULL DEFAULT 'default',
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, key)
            );

            CREATE TABLE IF NOT EXISTS inferred_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT 'default',
                fact TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_session_id TEXT,
                confirmed_by_user BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_user_preferences_user ON user_preferences(user_id);
            CREATE INDEX IF NOT EXISTS idx_inferred_facts_user ON inferred_facts(user_id, confidence);
        """)
        await conn.commit()

    async def initialize(self):
        conn = await self._get_conn()
        await self._init_schema(conn)

    async def close(self):
        if self._local_conn:
            await self._local_conn.close()
            self._local_conn = None

    async def set_preference(
        self,
        user_id: str,
        key: str,
        value: Any,
        category: str = "general"
    ) -> None:
        conn = await self._get_conn()
        val_str = _serialize_value(value)
        now = datetime.now(timezone.utc).isoformat()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            await conn.execute(
                """
                INSERT INTO user_preferences (user_id, key, value, category, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (user_id, key, val_str, category, now)
            )
            await conn.commit()

    async def get_preference(
        self,
        user_id: str,
        key: str,
        default: Any = None
    ) -> Any:
        conn = await self._get_conn()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            cursor = await conn.execute(
                "SELECT value FROM user_preferences WHERE user_id = ? AND key = ?",
                (user_id, key)
            )
            row = await cursor.fetchone()
            if not row:
                return default
            return _parse_stored_value(row["value"])

    async def list_preferences(self, user_id: str = "default") -> Dict[str, Any]:
        conn = await self._get_conn()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            cursor = await conn.execute(
                "SELECT key, value FROM user_preferences WHERE user_id = ? ORDER BY key ASC",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return {row["key"]: _parse_stored_value(row["value"]) for row in rows}

    async def list_preference_records(self, user_id: str = "default") -> List[PreferenceRecord]:
        conn = await self._get_conn()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            cursor = await conn.execute(
                "SELECT user_id, key, value, category, updated_at FROM user_preferences WHERE user_id = ? ORDER BY category, key ASC",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return [
                PreferenceRecord(
                    user_id=row["user_id"],
                    key=row["key"],
                    value=_parse_stored_value(row["value"]),
                    category=row["category"],
                    updated_at=str(row["updated_at"]) if row["updated_at"] else None
                )
                for row in rows
            ]

    async def delete_preference(self, user_id: str, key: str) -> bool:
        conn = await self._get_conn()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            cursor = await conn.execute(
                "DELETE FROM user_preferences WHERE user_id = ? AND key = ?",
                (user_id, key)
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def record_inferred_fact(
        self,
        user_id: str,
        fact: str,
        confidence: float,
        session_id: Optional[str] = None
    ) -> int:
        conf = max(0.0, min(1.0, float(confidence)))
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            cursor = await conn.execute(
                """
                INSERT INTO inferred_facts (user_id, fact, confidence, source_session_id, confirmed_by_user, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (user_id, fact.strip(), conf, session_id, now, now)
            )
            await conn.commit()
            return cursor.lastrowid

    async def list_facts(
        self,
        user_id: str = "default",
        min_confidence: float = 0.6
    ) -> List[FactRecord]:
        conn = await self._get_conn()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            cursor = await conn.execute(
                """
                SELECT id, user_id, fact, confidence, source_session_id, confirmed_by_user, created_at, updated_at
                FROM inferred_facts
                WHERE user_id = ? AND (confidence >= ? OR confirmed_by_user = 1)
                ORDER BY confirmed_by_user DESC, confidence DESC, id DESC
                """,
                (user_id, min_confidence)
            )
            rows = await cursor.fetchall()
            return [
                FactRecord(
                    id=row["id"],
                    user_id=row["user_id"],
                    fact=row["fact"],
                    confidence=float(row["confidence"]),
                    source_session_id=row["source_session_id"],
                    confirmed_by_user=bool(row["confirmed_by_user"]),
                    created_at=str(row["created_at"]) if row["created_at"] else None,
                    updated_at=str(row["updated_at"]) if row["updated_at"] else None,
                )
                for row in rows
            ]

    async def confirm_fact(self, fact_id: int) -> bool:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            cursor = await conn.execute(
                "UPDATE inferred_facts SET confirmed_by_user = 1, updated_at = ? WHERE id = ?",
                (now, fact_id)
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete_fact(self, fact_id: int) -> bool:
        conn = await self._get_conn()
        lock = getattr(self.db, "_lock", self._lock)
        async with lock:
            cursor = await conn.execute(
                "DELETE FROM inferred_facts WHERE id = ?",
                (fact_id,)
            )
            await conn.commit()
            return cursor.rowcount > 0
