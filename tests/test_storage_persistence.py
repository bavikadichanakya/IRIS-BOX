import pytest
import asyncio
from src.storage.db import Database, redact_secrets
from src.agent.orchestrator import IRISOrchestrator


@pytest.mark.asyncio
async def test_session_creation_and_turn_persistence():
    db = Database(":memory:")
    await db.connect()
    try:
        session_id = "sess_001"
        device_id = "device_pod_1"

        # Create/Update session
        sess = await db.create_or_update_session(
            session_id=session_id,
            device_id=device_id,
            metadata={"location": "living_room"}
        )
        assert sess is not None
        assert sess["session_id"] == session_id
        assert sess["device_id"] == device_id
        assert sess["metadata"]["location"] == "living_room"

        # Save turn
        turn_id = await db.save_turn(
            session_id=session_id,
            user_prompt="Turn on the kitchen lights",
            assistant_response="Turning on kitchen lights now",
            tool_calls=[{"name": "home_automation", "args": {"action": "on"}}],
            trace_ids=["trace_abc123"],
            duration_ms=120.5,
            metadata={"confidence": 0.98},
            device_id=device_id
        )
        assert turn_id > 0

        # Retrieve recent turns
        turns = await db.get_recent_turns(session_id, limit=10)
        assert len(turns) == 1
        turn = turns[0]
        assert turn["session_id"] == session_id
        assert turn["turn_index"] == 0
        assert turn["user_input"] == "Turn on the kitchen lights"
        assert turn["assistant_response"] == "Turning on kitchen lights now"
        assert turn["metadata"]["duration_ms"] == 120.5
        assert turn["metadata"]["trace_ids"] == ["trace_abc123"]

        # Add second turn
        turn_id_2 = await db.save_turn(
            session_id=session_id,
            user_prompt="What's the weather today?",
            assistant_response="It is sunny and 72 degrees",
            device_id=device_id
        )
        assert turn_id_2 > turn_id

        turns_all = await db.get_recent_turns(session_id, limit=10)
        assert len(turns_all) == 2
        assert turns_all[0]["turn_index"] == 0
        assert turns_all[1]["turn_index"] == 1
        assert turns_all[1]["user_input"] == "What's the weather today?"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_restart_recovery(tmp_path):
    db_file = str(tmp_path / "persistent_test.db")

    # Instance 1: Write session & turn
    db1 = Database(db_file)
    await db1.connect()
    session_id = "sess_restart_123"
    await db1.create_or_update_session(session_id=session_id, device_id="device_pod_restart")
    await db1.save_turn(
        session_id=session_id,
        user_prompt="Remember my favorite color is blue",
        assistant_response="I will remember that your favorite color is blue."
    )
    await db1.close()

    # Instance 2: Re-open DB from file and verify retention
    db2 = Database(db_file)
    await db2.connect()
    try:
        turns = await db2.get_recent_turns(session_id, limit=10)
        assert len(turns) == 1
        assert turns[0]["user_input"] == "Remember my favorite color is blue"
        assert turns[0]["assistant_response"] == "I will remember that your favorite color is blue."

        meta = await db2.get_session_metadata(session_id)
        assert meta is not None
        assert meta["device_id"] == "device_pod_restart"
    finally:
        await db2.close()


@pytest.mark.asyncio
async def test_session_isolation():
    db = Database(":memory:")
    await db.connect()
    try:
        sess_A = "session_alpha"
        sess_B = "session_beta"

        await db.save_turn(sess_A, "Hello from A", "Hi A")
        await db.save_turn(sess_B, "Hello from B", "Hi B")
        await db.save_turn(sess_A, "Second message from A", "Hi again A")

        turns_A = await db.get_recent_turns(sess_A, limit=10)
        turns_B = await db.get_recent_turns(sess_B, limit=10)

        assert len(turns_A) == 2
        assert len(turns_B) == 1

        # Verify no cross contamination
        for t in turns_A:
            assert t["session_id"] == sess_A
            assert "B" not in t["user_input"]

        for t in turns_B:
            assert t["session_id"] == sess_B
            assert "A" not in t["user_input"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_tool_execution_and_audit_logging():
    db = Database(":memory:")
    await db.connect()
    try:
        session_id = "sess_audit_test"
        trace_id = "trace_xyz987"
        device_id = "pod_audit_01"

        # Record tool execution
        exec_id = await db.record_tool_execution(
            session_id=session_id,
            tool_name="home_automation",
            status="SUCCEEDED",
            duration_ms=45.2,
            arguments={"device": "light", "state": "on"},
            result={"status": "ok"},
            trace_id=trace_id
        )
        assert exec_id > 0

        # Record audit event
        audit_id = await db.record_audit_event(
            event_type="tool.invoked",
            payload={"tool_name": "home_automation", "capability": "LIGHT_CONTROL"},
            correlation_id=trace_id,
            device_id=device_id
        )
        assert audit_id > 0

        # Direct DB verification
        async with db._conn.execute("SELECT * FROM tool_executions WHERE id = ?", (exec_id,)) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row["session_id"] == session_id
            assert row["tool_name"] == "home_automation"
            assert row["status"] == "SUCCEEDED"
            assert row["trace_id"] == trace_id

        async with db._conn.execute("SELECT * FROM audit_logs WHERE id = ?", (audit_id,)) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row["event_type"] == "tool.invoked"
            assert row["correlation_id"] == trace_id
            assert row["device_id"] == device_id
    finally:
        await db.close()


def test_secret_redaction():
    raw_str = "My api key is sk-1234567890abcdef12345678 and auth Bearer secret_token_xyz"
    redacted_str = redact_secrets(raw_str)
    assert "sk-1234567890abcdef12345678" not in redacted_str
    assert "Bearer [REDACTED]" in redacted_str

    data = {
        "api_key": "supersecretkey123",
        "nested": {
            "token": "tok_abcdef123456",
            "normal": "hello"
        },
        "list": [{"password": "pass123"}, "clean"]
    }
    redacted_data = redact_secrets(data)
    assert redacted_data["api_key"] == "[REDACTED]"
    assert redacted_data["nested"]["token"] == "[REDACTED]"
    assert redacted_data["nested"]["normal"] == "hello"
    assert redacted_data["list"][0]["password"] == "[REDACTED]"
    assert redacted_data["list"][1] == "clean"


@pytest.mark.asyncio
async def test_orchestrator_storage_integration():
    db = Database(":memory:")
    await db.connect()
    try:
        orchestrator = IRISOrchestrator(
            api_base="http://localhost:11434/v1",
            api_key="mock",
            database=db
        )

        session_id = "orchestrator_sess_1"
        device_id = "pod_01"
        trace_id = "trace_orch_01"

        # Call process_request (mock LLM will fail or return no function call, but turn should persist)
        res = orchestrator.process_request(
            user_prompt="Hello IRIS",
            session_id=session_id,
            device_id=device_id,
            trace_id=trace_id
        )

        turns = await db.get_recent_turns(session_id, limit=10)
        assert len(turns) == 1
        assert turns[0]["user_input"] == "Hello IRIS"
        assert turns[0]["session_id"] == session_id
    finally:
        await db.close()
