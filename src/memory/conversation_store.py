import sqlite3
import json
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class ConversationTurn(BaseModel):
    turn_id: str
    session_id: str
    user_query: str
    assistant_response: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)

class SQLiteConversationStore:
    """
    Persistent SQLite-backed turn and session store for conversational continuity.
    """
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        if self.db_path == ":memory:":
            # Keep a persistent connection open so in-memory DB survives between operations
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._conn = None
        self._init_db()

    def _get_connection(self):
        if self._conn is not None:
            return self._conn
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_query TEXT NOT NULL,
                    assistant_response TEXT,
                    tool_calls TEXT,
                    tool_results TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_session ON conversation_turns (session_id, timestamp)
            """)
            conn.commit()
        finally:
            if self._conn is None:
                conn.close()

    def save_turn(self, turn: ConversationTurn):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO conversation_turns 
                (turn_id, session_id, user_query, assistant_response, tool_calls, tool_results, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                turn.turn_id,
                turn.session_id,
                turn.user_query,
                turn.assistant_response,
                json.dumps(turn.tool_calls),
                json.dumps(turn.tool_results),
                turn.timestamp
            ))
            conn.commit()
        finally:
            if self._conn is None:
                conn.close()

    def get_history(self, session_id: str, limit: int = 20) -> List[ConversationTurn]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT turn_id, session_id, user_query, assistant_response, tool_calls, tool_results, timestamp
                FROM conversation_turns
                WHERE session_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (session_id, limit))
            rows = cursor.fetchall()
            turns = []
            for r in rows:
                turns.append(ConversationTurn(
                    turn_id=r[0],
                    session_id=r[1],
                    user_query=r[2],
                    assistant_response=r[3],
                    tool_calls=json.loads(r[4] or "[]"),
                    tool_results=json.loads(r[5] or "[]"),
                    timestamp=r[6]
                ))
            return turns
        finally:
            if self._conn is None:
                conn.close()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
