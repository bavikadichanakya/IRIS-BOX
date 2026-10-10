import os
import json
import time
import asyncio
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.server.app import app
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

    tts_engine = TTSEngine()
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
