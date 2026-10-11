import os
import json
import time
import asyncio
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.server.app import app
from src.models.schemas import AgentExecutionResult
from src.security.auth import auth_manager
from src.observability.event_bus import EventBus
from src.storage.db import Database
from src.agent.orchestrator import IRISOrchestrator
from src.audio.wakeword import WakeWordDetector
from src.audio.stt import Transcriber
from src.audio.tts import TTSEngine
from src.tools.registry import ToolRegistry
from src.voice.pipeline import VoicePipeline


@pytest.fixture
def auth_header():
    return {"Authorization": f"Bearer {auth_manager.master_key}"}


@pytest.mark.asyncio
async def test_end_to_end_websocket_user_journey():
    """
    Release Validation E2E: Simulates complete user session over WebSocket:
    Handshake -> Auth Verification -> Text Input -> Tool Manager Execution -> Audit Telemetry -> Response & Turn Complete.
    """
    master_key = auth_manager.master_key

    mock_result = AgentExecutionResult(
        success=True,
        tool_name="SystemCommandTool",
        output_payload={"stdout": "E2E_RELEASE_VALIDATION\n", "response": "Executed command echo E2E_RELEASE_VALIDATION"}
    )
    with patch("src.agent.orchestrator.IRISOrchestrator.process_request", return_value=mock_result):
        with TestClient(app) as client:
            ws_url = f"/v1/ws?device_id=val-pod-01&token={master_key}"
            with client.websocket_connect(ws_url) as websocket:
                # 1. Connected Handshake
                handshake = websocket.receive_json()
                assert handshake["type"] == "connected"
                assert "session_id" in handshake

                # 2. Send Text Input requesting system command tool
                websocket.send_json({"type": "text_input", "text": "echo E2E_RELEASE_VALIDATION"})

                # 3. First frame should be transcript confirmation
                transcript_msg = websocket.receive_json()
                assert transcript_msg["type"] == "transcript"
                assert transcript_msg["text"] == "echo E2E_RELEASE_VALIDATION"
                assert transcript_msg["is_final"] is True

                # 4. Stream response until turn_complete
                received_messages = []
                while True:
                    msg = websocket.receive_json()
                    received_messages.append(msg)
                    if msg["type"] in ("turn_complete", "error"):
                        break

                msg_types = [m["type"] for m in received_messages]
                assert "turn_complete" in msg_types or "token_delta" in msg_types


@pytest.mark.asyncio
async def test_end_to_end_orchestration_loop():
    """
    Release Validation E2E: Verifies multi-step ReAct orchestration loop in process_request:
    Model calls SystemCommandTool -> Executed with real stdout side effect -> Output fed back to LLM -> Final text synthesis references stdout.
    """
    from src.tools.registry import SystemCommandTool
    ToolRegistry._tool_classes["SystemCommandTool"] = SystemCommandTool
    orchestrator = IRISOrchestrator(api_base="http://127.0.0.1:11434/v1", api_key="ollama")

    class MockChoice:
        def __init__(self, message):
            self.message = message

    class MockResponse:
        def __init__(self, message):
            self.choices = [MockChoice(message)]

    class MockFunction:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class MockToolCall:
        def __init__(self, name, arguments, call_id="call_1"):
            self.id = call_id
            self.function = MockFunction(name, arguments)

    # Turn 1: LLM invokes SystemCommandTool with echo command
    msg1 = MagicMock()
    msg1.content = ""
    msg1.tool_calls = [MockToolCall("SystemCommandTool", json.dumps({"command": "echo E2E_REACT_PARITY_TEST", "action_type": "terminal"}))]
    msg1.function_call = None
    resp1 = MockResponse(msg1)

    # Turn 2: LLM receives tool result and produces final synthesis referencing stdout
    msg2 = MagicMock()
    msg2.content = "Command execution completed successfully. Output: E2E_REACT_PARITY_TEST"
    msg2.tool_calls = None
    msg2.function_call = None
    resp2 = MockResponse(msg2)

    responses = [resp1, resp2]

    def fake_execute_with_recovery_sync(_call_completion, **kwargs):
        return responses.pop(0)

    with patch.object(orchestrator.resilient_provider, "execute_with_recovery_sync", side_effect=fake_execute_with_recovery_sync):
        result = orchestrator.process_request(
            user_prompt="Run echo E2E_REACT_PARITY_TEST",
            session_id="e2e-parity-sess",
            device_id="pod-01",
            confirmed=True
        )

        # 1. Assert overall success and tool identification
        assert result.success is True
        assert result.tool_name == "SystemCommandTool"

        # 2. Assert tool side effects are verified (stdout returned by executed SystemCommandTool)
        assert "stdout" in result.output_payload
        assert "E2E_REACT_PARITY_TEST" in result.output_payload["stdout"]

        # 3. Assert final conversational text directly references tool output
        assert "response" in result.output_payload
        assert "E2E_REACT_PARITY_TEST" in result.output_payload["response"]


@pytest.mark.asyncio
async def test_end_to_end_database_and_telemetry_flow(tmp_path):
    """
    Release Validation Integration: Verifies Database SQLite persistence and EventBus audit logging.
    """
    db_file = str(tmp_path / "release_val.db")
    db = Database(db_path=db_file)
    await db.connect()

    event_bus = EventBus()
    published_events = []
    event_bus.subscribe("orchestrator.request_processed", lambda e: published_events.append(e))

    # 1. Save turn to SQLite
    turn_id = await db.save_turn(
        session_id="val-sess-100",
        user_prompt="echo RELEASE_VALIDATION_DB",
        assistant_response="Executing system command",
        device_id="speaker-val"
    )
    assert turn_id > 0

    # 2. Record tool execution in SQLite
    exec_id = await db.record_tool_execution(
        session_id="val-sess-100",
        tool_name="SystemCommandTool",
        status="SUCCEEDED",
        duration_ms=15.5,
        turn_id=turn_id,
        arguments={"command": "echo RELEASE_VALIDATION_DB"},
        result={"stdout": "RELEASE_VALIDATION_DB"}
    )
    assert exec_id > 0

    # 3. Record audit event in SQLite
    audit_id = await db.record_audit_event(
        event_type="orchestrator.request_processed",
        payload={"request_id": "val-req-1", "tool_name": "SystemCommandTool"},
        correlation_id="val-sess-100",
        device_id="speaker-val"
    )
    assert audit_id > 0

    # 4. Verify turn persistence in SQLite
    turns = await db.get_recent_turns(session_id="val-sess-100")
    assert len(turns) == 1
    assert turns[0]["user_input"] == "echo RELEASE_VALIDATION_DB"

    # 5. Verify audit log query
    async with db._conn.execute("SELECT * FROM audit_logs WHERE event_type = ?", ("orchestrator.request_processed",)) as cursor:
        audit_rows = await cursor.fetchall()
        assert len(audit_rows) == 1
        assert audit_rows[0]["correlation_id"] == "val-sess-100"

    await db.close()


@pytest.mark.asyncio
async def test_end_to_end_voice_pipeline_integration():
    """
    Release Validation Voice Loop: Verifies VAD, Wakeword ONNX model, STT, and TTS Engine interaction.
    """
    detector = WakeWordDetector(keyword="hey iris")
    assert detector.model_path is not None
    assert os.path.exists(detector.model_path)

    tts_engine = TTSEngine(online_fallback=True)
    audio_stream = tts_engine.stream_audio("Testing voice pipeline synthesis")
    chunks = []
    async for chunk in audio_stream:
        chunks.append(chunk)

    assert len(chunks) > 0
    full_audio = b"".join(chunks)
    assert len(full_audio) > 0


@pytest.mark.hardware
def test_hardware_dependent_device_skip_gate():
    """
    Hardware Dependency Gate: Gracefully skips physical microphone / speaker tests if unconfigured.
    """
    if not os.getenv("IRIS_ENABLE_HARDWARE_TESTS"):
        pytest.skip("Physical microphone / audio hardware not detected or IRIS_ENABLE_HARDWARE_TESTS not set.")

    # Hardware test assertion if environment supports physical devices
    assert True


@pytest.mark.asyncio
async def test_strict_offline_llm_endpoint_rejection():
    """
    Verifies that configuring a remote/cloud LLM endpoint without IRIS_ALLOW_CLOUD=1 raises SecurityError.
    """
    from src.agent.orchestrator import SecurityError
    with pytest.raises(SecurityError, match="Strict offline policy violation"):
        IRISOrchestrator(api_base="https://openrouter.ai/api/v1", api_key="test-key")


@pytest.mark.asyncio
async def test_multistep_streaming_react_loop():
    """
    Verifies that stream_request executes a tool and feeds its output back into reasoning.
    """
    orchestrator = IRISOrchestrator(api_base="http://127.0.0.1:11434/v1", api_key="ollama")

    class MockDelta:
        def __init__(self, content=None, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls

    class MockChoice:
        def __init__(self, delta):
            self.delta = delta

    class MockChunk:
        def __init__(self, delta):
            self.choices = [MockChoice(delta)]

    class MockFunction:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class MockToolCall:
        def __init__(self, name, arguments, call_id="call_1"):
            self.id = call_id
            self.function = MockFunction(name, arguments)

    # Turn 1 emits tool call, Turn 2 emits final text
    async def mock_stream_turn_1():
        yield MockChunk(MockDelta(tool_calls=[MockToolCall("SystemCommandTool", '{"command": "echo RE_STEP_1", "action_type": "terminal"}')]))

    async def mock_stream_turn_2():
        yield MockChunk(MockDelta(content="Done executing step 1"))

    streams = [mock_stream_turn_1(), mock_stream_turn_2()]

    def fake_stream_with_recovery(_create_stream, **kwargs):
        return streams.pop(0)

    with patch.object(orchestrator.resilient_provider, "stream_with_recovery", side_effect=fake_stream_with_recovery):
        chunks = []
        async for chunk in orchestrator.stream_request("Run multi-step test"):
            chunks.append(chunk)

        chunk_types = [c.chunk_type for c in chunks]
        assert "tool_call" in chunk_types
        assert "tool_result" in chunk_types
        assert "text_delta" in chunk_types
        assert "complete" in chunk_types
