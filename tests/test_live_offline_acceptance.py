import os
import json
import socket
import shutil
import contextlib
import urllib.request
import pytest
from pathlib import Path

from src.audio.tts import TTSEngine
from src.audio.stt import Transcriber
from src.skills.core.system_command import SystemCommandSkill


from src.security.airgap import socket_air_gap_guard, LOOPBACK_HOSTS, AirGapViolationError


def check_ollama_prerequisites(model_name: str = "qwen2.5:7b-instruct") -> bool:
    """Verify local Ollama daemon is reachable and has the required model."""
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "IRIS-Acceptance"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode())
            models = [m.get("name", "") for m in data.get("models", [])]
            return any(model_name in m for m in models)
    except Exception:
        return False


def check_piper_prerequisites() -> bool:
    """Verify Piper binary and model exist locally."""
    piper_path = Path("models/piper/piper.exe")
    model_path = Path("models/piper/en_US-lessac-medium.onnx")
    if piper_path.exists() and model_path.exists():
        return True
    return bool(shutil.which("piper"))


def test_socket_guard_blocks_non_loopback_network_attempts():
    """
    Verify socket_air_gap_guard intercepts any non-loopback connection attempts
    and raises RuntimeError('AIR_GAP_VIOLATION...').
    """
    with socket_air_gap_guard():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(RuntimeError, match="AIR_GAP_VIOLATION"):
            s.connect(("8.8.8.8", 53))

        # Local loopback must not raise AIR_GAP_VIOLATION (may fail with normal ConnectionRefused)
        s_local = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s_local.connect(("127.0.0.1", 11434))
        except (ConnectionRefusedError, OSError):
            pass  # Allowed to fail with OS connection error, but not blocked by air-gap guard


def test_strict_zero_mock_offline_engines_configuration():
    """
    Verify offline engines enforce online_fallback=False and reject mock fallbacks.
    """
    tts = TTSEngine(online_fallback=False)
    assert tts.online_fallback is False

    stt = Transcriber(model_name="base", fallback_mock=False)
    assert stt.fallback_mock is False
    assert stt.mock_mode is False


@pytest.mark.asyncio
async def test_live_offline_unmocked_end_to_end_acceptance():
    """
    Strict Zero-Mock Offline Acceptance Test:
    1. Socket guard active (assert RuntimeError on non-loopback).
    2. Real STT engine transcribing local PCM audio.
    3. Real local harmless tool invocation (SystemCommandSkill running 'echo IRIS_VERIFIED_OFFLINE').
    4. Real Ollama loopback endpoint querying 'qwen2.5:7b-instruct'.
    5. Real Piper TTS synthesis validating binary RIFF WAV header generation.
    6. Assert tool stdout is accurately reflected in the LLM's final synthesized response.
    """
    # Hardware prerequisite diagnostics and clean skips
    if not check_piper_prerequisites():
        pytest.skip(
            "Hardware prerequisite absent: Local Piper TTS binary or model not found at models/piper/"
        )

    if not check_ollama_prerequisites("qwen2.5:7b-instruct"):
        pytest.skip(
            "Hardware prerequisite absent: Local Ollama daemon unreachable or qwen2.5:7b-instruct model not loaded."
        )

    # Enforce air-gap socket guard for entire end-to-end execution
    with socket_air_gap_guard():
        # 1. Initialize strictly offline engines
        tts = TTSEngine(online_fallback=False)
        stt = Transcriber(model_name="base", fallback_mock=False)

        assert tts.online_fallback is False
        assert stt.mock_mode is False

        # 2. Real local harmless tool invocation: SystemCommandSkill
        skill = SystemCommandSkill(allowed_commands={"echo"})
        tool_res = await skill.execute({"command": "echo IRIS_VERIFIED_OFFLINE"})

        assert tool_res.success is True, f"Tool execution failed: {tool_res.error}"
        tool_stdout = tool_res.output.get("stdout", "").strip()
        assert tool_stdout == "IRIS_VERIFIED_OFFLINE", f"Unexpected tool stdout: {tool_stdout}"

        # 3. Real STT engine transcribing local PCM audio
        # Generate local PCM audio using Piper
        pcm_speech = await tts.synthesize("Echo IRIS_VERIFIED_OFFLINE")
        assert pcm_speech.startswith(b"RIFF"), "Local speech synthesis must produce valid RIFF WAV"
        transcribed_text = stt.transcribe_pcm(pcm_speech)
        assert isinstance(transcribed_text, str)
        assert len(transcribed_text) > 0, "STT must produce non-empty transcription from local audio"

        # 4. Real Ollama loopback endpoint querying qwen2.5:7b-instruct
        prompt = (
            f"The system command executed successfully with stdout: '{tool_stdout}'. "
            f"Please state in one sentence that the status is confirmed with the exact token {tool_stdout}."
        )
        payload = json.dumps({
            "model": "qwen2.5:7b-instruct",
            "prompt": prompt,
            "options": {
                "num_predict": 30,
                "temperature": 0.1,
            },
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=120.0) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))

        llm_response = resp_data.get("response", "")
        assert len(llm_response) > 0, "Ollama LLM response must not be empty"

        # Assert tool stdout is accurately reflected in LLM response
        assert "IRIS_VERIFIED_OFFLINE" in llm_response, (
            f"Tool stdout 'IRIS_VERIFIED_OFFLINE' was not reflected in LLM response: '{llm_response}'"
        )

        # 5. Real Piper TTS synthesis validating binary RIFF WAV header generation
        final_audio = await tts.synthesize(llm_response)
        assert isinstance(final_audio, bytes)
        assert final_audio.startswith(b"RIFF"), (
            f"Synthesized audio must have binary RIFF WAV header, got: {final_audio[:4]}"
        )
        assert len(final_audio) >= 1000, (
            f"Synthesized audio length too small ({len(final_audio)} bytes)"
        )


from fastapi.testclient import TestClient
from src.server.app import app
from src.security.auth import auth_manager
import asyncio


def test_authenticated_laptop_agent_ws_journey():
    """
    End-to-end acceptance test for the authenticated laptop-agent lifecycle (F-02, F-07, F-18):
    1. Unauthorized agent connection is rejected immediately.
    2. Authorized agent connects, sends registration handshake, receives server ACK.
    3. Device is registered in FleetManager as online with capabilities.
    4. Hub dispatches an operator command; agent receives, executes, and acks.
    5. Agent sends ping, receives pong.
    """
    with TestClient(app) as client:
        # 1. Negative test: unauthorized connection
        with client.websocket_connect("/ws/agent") as ws_unauth:
            ws_unauth.send_json({
                "type": "register",
                "device": "rogue_laptop",
                "token": "invalid_untrusted_token",
                "capabilities": ["run_command"]
            })
            resp = ws_unauth.receive_json()
            assert resp.get("type") == "error"
            assert resp.get("error") == "UNAUTHORIZED"

        # 2. Positive test: authenticated connection
        valid_token = auth_manager.get_master_key()
        with client.websocket_connect("/ws/agent") as ws:
            ws.send_json({
                "type": "register",
                "device": "laptop1",
                "token": valid_token,
                "capabilities": ["open_app", "system_status", "volume", "hotkey"]
            })
            ack = ws.receive_json()
            assert ack.get("type") == "registered"
            assert ack.get("status") == "ok"
            assert ack.get("device") == "laptop1"

            # 3. FleetManager verification
            fleet_mgr = getattr(app.state, "fleet_manager", None)
            assert fleet_mgr is not None
            device = fleet_mgr.get_speaker("laptop1")
            assert device is not None
            assert device.status == "online"
            assert device.device_type == "laptop"

            # 4. Ping-Pong Heartbeat verification
            ws.send_json({"type": "ping", "timestamp": 12345.0})
            pong = ws.receive_json()
            assert pong.get("type") == "pong"

            # 5. Device command dispatch verification
            from src.server.websocket import ws_manager

            sess_id = ws_manager.device_to_session.get("laptop1")
            assert sess_id is not None
            server_ws = ws_manager.active_connections.get(sess_id)
            assert server_ws is not None

            # Server sends down to client
            asyncio.run(server_ws.send_json({
                "type": "device_command",
                "command_id": "cmd-accept-001",
                "action": "system_status",
                "payload": {"target": "workstation"}
            }))

            # Client receives command
            cmd_received = ws.receive_json()
            assert cmd_received.get("action") == "system_status"
            assert cmd_received.get("command_id") == "cmd-accept-001"

            # Client responds with tool result ACK
            ws.send_json({
                "type": "tool_result",
                "id": cmd_received.get("command_id"),
                "device": "laptop1",
                "result": {"success": True, "message": "System status nominal: CPU 12%, RAM 45%"}
            })

            # Check that ping still works after tool execution
            ws.send_json({"type": "ping", "timestamp": 12346.0})
            pong2 = ws.receive_json()
            assert pong2.get("type") == "pong"
