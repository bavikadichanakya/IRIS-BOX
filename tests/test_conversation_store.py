import pytest
from src.memory.conversation_store import SQLiteConversationStore, ConversationTurn

def test_sqlite_conversation_store_crud():
    store = SQLiteConversationStore(":memory:")
    turn = ConversationTurn(
        turn_id="turn-001",
        session_id="session-abc",
        user_query="Turn on living room light",
        assistant_response="Light has been switched on.",
        tool_calls=[{"tool": "HomeAssistant", "action": "turn_on"}],
        tool_results=[{"status": "SUCCEEDED", "output": {"power": "on"}}]
    )
    store.save_turn(turn)

    history = store.get_history("session-abc")
    assert len(history) == 1
    assert history[0].turn_id == "turn-001"
    assert history[0].user_query == "Turn on living room light"
    assert history[0].tool_calls[0]["tool"] == "HomeAssistant"
    assert history[0].tool_results[0]["status"] == "SUCCEEDED"

def test_sqlite_conversation_store_session_isolation():
    store = SQLiteConversationStore(":memory:")
    turn1 = ConversationTurn(turn_id="t1", session_id="s1", user_query="Hi")
    turn2 = ConversationTurn(turn_id="t2", session_id="s2", user_query="Hello")

    store.save_turn(turn1)
    store.save_turn(turn2)

    assert len(store.get_history("s1")) == 1
    assert len(store.get_history("s2")) == 1
