import asyncio
import aiosqlite
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import json
import re


def redact_secrets(data: Any) -> Any:
    """Recursively redact API keys, tokens, and secrets from strings, lists, or dicts."""
    if isinstance(data, str):
        data = re.sub(r'(sk-[a-zA-Z0-9]{20,})', '[REDACTED]', data)
        data = re.sub(r'(Bearer\s+[a-zA-Z0-9\._\-]+)', 'Bearer [REDACTED]', data)
        return data
    elif isinstance(data, dict):
        sensitive_keys = {"api_key", "apikey", "secret", "token", "password", "authorization", "auth_header"}
        redacted = {}
        for k, v in data.items():
            if k.lower() in sensitive_keys:
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = redact_secrets(v)
        return redacted
    elif isinstance(data, list):
        return [redact_secrets(item) for item in data]
    return data


class Database:
    """Async SQLite database for persistent conversation logs, sessions, turns, tool executions, latency metrics, and audit tracking."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self):
        """Establish database connection and initialize schema."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._init_schema()

    async def close(self):
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _init_schema(self):
        """Initialize database schema with tables and indexes."""
        await self._conn.execute("PRAGMA foreign_keys = ON;")
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                device_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                user_input TEXT NOT NULL,
                assistant_response TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tool_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_id INTEGER,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms REAL DEFAULT 0.0,
                arguments_json TEXT,
                result_json TEXT,
                error TEXT,
                trace_id TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                correlation_id TEXT,
                device_id TEXT,
                payload_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

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

            CREATE INDEX IF NOT EXISTS idx_sessions_device ON sessions(device_id);
            CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, turn_index);
            CREATE INDEX IF NOT EXISTS idx_tool_exec_session ON tool_executions(session_id);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_event ON audit_logs(event_type);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_correlation ON audit_logs(correlation_id);
            CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
            CREATE INDEX IF NOT EXISTS idx_latency_session ON latency_metrics(session_id);
            CREATE INDEX IF NOT EXISTS idx_errors_session ON errors(session_id);
        """)
        await self._conn.commit()

    async def _ensure_session_exists(self, session_id: str, device_id: Optional[str] = None):
        cursor = await self._conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,))
        if not await cursor.fetchone():
            now = datetime.now(timezone.utc).isoformat()
            await self._conn.execute(
                "INSERT INTO sessions (session_id, device_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, device_id, now, now)
            )

    async def create_or_update_session(
        self,
        session_id: str,
        device_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Insert or update a session record."""
        async with self._lock:
            safe_meta = redact_secrets(metadata) if metadata else {}
            meta_json = json.dumps(safe_meta) if safe_meta else None

            cursor = await self._conn.execute(
                "SELECT session_id, device_id, created_at, updated_at, metadata_json FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            row = await cursor.fetchone()
            now = datetime.now(timezone.utc).isoformat()

            if row is None:
                await self._conn.execute(
                    "INSERT INTO sessions (session_id, device_id, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
                    (session_id, device_id, now, now, meta_json)
                )
            else:
                existing_dev = device_id if device_id is not None else row["device_id"]
                existing_meta_str = meta_json if meta_json is not None else row["metadata_json"]
                await self._conn.execute(
                    "UPDATE sessions SET device_id = ?, updated_at = ?, metadata_json = ? WHERE session_id = ?",
                    (existing_dev, now, existing_meta_str, session_id)
                )
            await self._conn.commit()
            return await self.get_session_metadata(session_id)

    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session metadata dictionary for a session_id."""
        cursor = await self._conn.execute(
            "SELECT session_id, device_id, created_at, updated_at, metadata_json FROM sessions WHERE session_id = ?",
            (session_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        if res.get("metadata_json"):
            try:
                res["metadata"] = json.loads(res["metadata_json"])
            except Exception:
                res["metadata"] = {}
        else:
            res["metadata"] = {}
        return res

    async def save_turn(
        self,
        session_id: str,
        user_prompt: str,
        assistant_response: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        trace_ids: Optional[List[str]] = None,
        duration_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
        device_id: Optional[str] = None
    ) -> int:
        """Insert a conversation turn record into turns table and update session timestamps."""
        async with self._lock:
            await self._ensure_session_exists(session_id, device_id=device_id)

            cursor = await self._conn.execute(
                "SELECT COALESCE(MAX(turn_index), -1) as max_idx FROM turns WHERE session_id = ?",
                (session_id,)
            )
            row = await cursor.fetchone()
            next_idx = (row["max_idx"] if row else -1) + 1

            meta_dict = metadata.copy() if metadata else {}
            if tool_calls:
                meta_dict["tool_calls"] = tool_calls
            if trace_ids:
                meta_dict["trace_ids"] = trace_ids
            if duration_ms:
                meta_dict["duration_ms"] = duration_ms

            safe_meta = redact_secrets(meta_dict)
            safe_user_prompt = redact_secrets(user_prompt)
            safe_assistant_response = redact_secrets(assistant_response)

            cursor = await self._conn.execute(
                "INSERT INTO turns (session_id, turn_index, user_input, assistant_response, metadata_json) VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    next_idx,
                    safe_user_prompt if isinstance(safe_user_prompt, str) else str(safe_user_prompt),
                    safe_assistant_response if isinstance(safe_assistant_response, str) else str(safe_assistant_response),
                    json.dumps(safe_meta) if safe_meta else None
                )
            )
            turn_id = cursor.lastrowid
            now = datetime.now(timezone.utc).isoformat()
            await self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id)
            )
            await self._conn.commit()
            return turn_id

    async def get_recent_turns(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent turns for a session in chronological order (bounded by limit)."""
        cursor = await self._conn.execute(
            """
            SELECT id, session_id, turn_index, user_input, assistant_response, created_at, metadata_json
            FROM turns
            WHERE session_id = ?
            ORDER BY turn_index DESC
            LIMIT ?
            """,
            (session_id, limit)
        )
        rows = await cursor.fetchall()
        turns = []
        for r in reversed(rows):
            turn_dict = dict(r)
            if turn_dict.get("metadata_json"):
                try:
                    turn_dict["metadata"] = json.loads(turn_dict["metadata_json"])
                except Exception:
                    turn_dict["metadata"] = {}
            else:
                turn_dict["metadata"] = {}
            turns.append(turn_dict)
        return turns

    async def record_tool_execution(
        self,
        session_id: str,
        tool_name: str,
        status: str,
        duration_ms: float = 0.0,
        turn_id: Optional[int] = None,
        arguments: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> int:
        """Record a tool execution entry in tool_executions table."""
        async with self._lock:
            safe_args = redact_secrets(arguments) if arguments else None
            safe_res = redact_secrets(result) if result else None
            safe_err = redact_secrets(error) if error else None

            cursor = await self._conn.execute(
                """
                INSERT INTO tool_executions (
                    session_id, turn_id, tool_name, status, duration_ms, arguments_json, result_json, error, trace_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_id,
                    tool_name,
                    status,
                    duration_ms,
                    json.dumps(safe_args) if safe_args else None,
                    json.dumps(safe_res) if safe_res else None,
                    safe_err if isinstance(safe_err, str) else str(safe_err) if safe_err else None,
                    trace_id
                )
            )
            await self._conn.commit()
            return cursor.lastrowid

    async def record_audit_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        device_id: Optional[str] = None
    ) -> int:
        """Insert an operational audit log entry."""
        async with self._lock:
            safe_payload = redact_secrets(payload) if payload else {}
            cursor = await self._conn.execute(
                """
                INSERT INTO audit_logs (event_type, correlation_id, device_id, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event_type,
                    correlation_id,
                    device_id,
                    json.dumps(safe_payload) if safe_payload else None
                )
            )
            await self._conn.commit()
            return cursor.lastrowid

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

