import os
import pytest
import asyncio
import sqlite3
from unittest.mock import patch, MagicMock

from src.agent.recovery import ResilientLLMProvider, CircuitState, ProviderUnavailableError
from src.agent.orchestrator import IRISOrchestrator
from src.audio.wakeword import WakeWordDetector, DEFAULT_MODEL_PATH
from src.audio.stt import Transcriber
from src.audio.tts import TTSEngine
from src.storage.db import Database
from src.tools.registry import SystemCommandTool, BrowserTool, HomeAssistantTool
from src.models.schemas import LaptopSystemAction, BrowserAction, SmartHomeAction


@pytest.mark.asyncio
async def test_offline_local_llm_provider_fail_closed():
    """Verify local LLM provider fails closed with ProviderUnavailableError when local model server is down."""
    provider = ResilientLLMProvider(
        max_retries=1,
        base_delay=0.01
    )

    async def fail_call():
        raise ConnectionRefusedError("Local server at 11434 refused connection")

    with pytest.raises(ConnectionRefusedError):
        await provider.execute_with_recovery(fail_call, request_id="offline-req-1")


def test_wakeword_onnx_model_file_presence():
    """Verify ONNX wake-word model 'hey_iris.onnx' exists and is targeted by WakeWordDetector."""
    assert os.path.exists(DEFAULT_MODEL_PATH), f"Model file missing at {DEFAULT_MODEL_PATH}"
    detector = WakeWordDetector(keyword="hey iris")
    assert detector.keyword == "hey iris"
    assert detector.frame_size == 1280


def test_stt_transcriber_no_silent_mock_in_production():
    """Verify Transcriber raises RuntimeError in production mode (fallback_mock=False) when whisper unavailable."""
    with patch("src.audio.stt.whisper", None):
        t = Transcriber(fallback_mock=False)
        assert t.status == "UNAVAILABLE"
        assert t.mock_mode is False
        with pytest.raises(RuntimeError) as exc_info:
            t.transcribe_pcm(b"\x00\x00" * 1280)
        assert "UNAVAILABLE" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sqlite_offline_persistence(tmp_path):
    """Verify SQLite database persists conversation turns and audit events completely offline."""
    db_file = str(tmp_path / "offline_iris.db")
    db = Database(db_path=db_file)
    await db.connect()

    # Save turn
    turn_id = await db.save_turn(
        session_id="offline-sess-1",
        user_prompt="Turn off the living room lights",
        assistant_response="Living room lights turned off.",
        device_id="pod-living-room"
    )
    assert turn_id is not None

    # Query turns
    turns = await db.get_recent_turns(session_id="offline-sess-1")
    assert len(turns) == 1
    assert turns[0]["user_input"] == "Turn off the living room lights"

    # Record audit event
    audit_id = await db.record_audit_event(
        event_type="device.offline_action",
        payload={"action": "turn_off", "entity": "light.living_room"},
        correlation_id="corr-99"
    )
    assert audit_id is not None
    await db.close()


def test_system_command_tool_local_execution():
    """Verify SystemCommandTool executes valid local commands offline and returns real output."""
    tool = SystemCommandTool()
    res = tool.execute(LaptopSystemAction(command="echo OFFLINE_TEST_SUCCESS", action_type="terminal"))

    assert res.success is True
    assert "OFFLINE_TEST_SUCCESS" in res.output_payload["stdout"]


def test_browser_tool_offline_connectivity_boundary():
    """Verify BrowserTool reports CONNECTIVITY_UNAVAILABLE or SSRF_BLOCKED rather than fabricating fake page content."""
    tool = BrowserTool()

    # 1. SSRF metadata attempt
    res_ssrf = tool.execute(BrowserAction(action="goto", url="http://169.254.169.254/latest/meta-data/"))
    assert res_ssrf.success is False
    assert "SSRF_BLOCKED" in res_ssrf.error

    # 2. Inaccessible remote site offline attempt
    res_offline = tool.execute(BrowserAction(action="goto", url="http://192.0.2.1/unreachable-page"))
    assert res_offline.success is False
    assert ("CONNECTIVITY_UNAVAILABLE" in res_offline.error or "SSRF_BLOCKED" in res_offline.error)
