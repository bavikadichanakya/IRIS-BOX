import asyncio
import json
import pytest
from fastapi.testclient import TestClient

from src.server.app import app
from src.server.websocket import ws_manager, WebSocketConnectionManager
from src.server.protocol import (
    InboundConnectPayload,
    InboundPingPayload,
    InboundTextInputPayload,
    InboundAudioFramePayload,
    InboundCancelPayload,
    parse_inbound_message,
)
from src.observability.health import health_supervisor


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_protocol_message_parsing():
    """Verify inbound JSON message schemas parse correctly."""
    ping_data = {"type": "ping", "timestamp": 12345.6}
    ping_msg = parse_inbound_message(ping_data)
    assert isinstance(ping_msg, InboundPingPayload)
    assert ping_msg.timestamp == 12345.6

    connect_data = {
        "type": "connect",
        "version": "1.0",
        "device_id": "speaker-01",
        "capabilities": ["audio_out", "microphone"],
    }
    connect_msg = parse_inbound_message(connect_data)
    assert isinstance(connect_msg, InboundConnectPayload)
    assert connect_msg.device_id == "speaker-01"

    text_data = {"type": "text_input", "text": "Turn on the lights"}
    text_msg = parse_inbound_message(text_data)
    assert isinstance(text_msg, InboundTextInputPayload)
    assert text_msg.text == "Turn on the lights"

    cancel_data = {"type": "cancel", "request_id": "req-101"}
    cancel_msg = parse_inbound_message(cancel_data)
    assert isinstance(cancel_msg, InboundCancelPayload)
    assert cancel_msg.request_id == "req-101"

    with pytest.raises(ValueError):
        parse_inbound_message({"type": "unknown_type"})


from src.security.auth import auth_manager


def test_websocket_connection_handshake(client):
    """Test connection handshake, initial 'connected' envelope, and version negotiation."""
    url = f"/ws?device_id=test-speaker-01&token={auth_manager.master_key}"
    with client.websocket_connect(url) as websocket:
        # Receive initial connected message
        data = websocket.receive_json()
        assert data["type"] == "connected"
        assert data["version"] == "1.0"
        assert "session_id" in data
        assert "server_time" in data


def test_websocket_ping_pong_heartbeat(client):
    """Test sending ping message returns pong response."""
    url = f"/ws?token={auth_manager.master_key}"
    with client.websocket_connect(url) as websocket:
        _ = websocket.receive_json()  # Handshake connected payload

        # Send ping
        websocket.send_json({"type": "ping", "timestamp": 1000.0})
        resp = websocket.receive_json()
        assert resp["type"] == "pong"
        assert resp["timestamp"] == 1000.0


def test_websocket_text_input_streaming(client):
    """Test text input streaming yields transcript, tokens, and turn_complete."""
    from unittest.mock import patch, MagicMock
    from src.models.schemas import AgentExecutionResult

    mock_result = AgentExecutionResult(success=True, tool_name="", output_payload={"response": "Hello!"})
    if hasattr(app.state, "orchestrator") and app.state.orchestrator:
        p = patch.object(app.state.orchestrator, "process_request", return_value=mock_result)
    else:
        p = patch("src.agent.orchestrator.IRISOrchestrator.process_request", return_value=mock_result)

    with p:
        url = f"/v1/ws?device_id=living-room&token={auth_manager.master_key}"
        with client.websocket_connect(url) as websocket:
            handshake = websocket.receive_json()
            assert handshake["type"] == "connected"

            # Send text input
            websocket.send_json({"type": "text_input", "text": "Hello IRIS"})

            # First message should be transcript confirmation
            msg1 = websocket.receive_json()
            assert msg1["type"] == "transcript"
            assert msg1["text"] == "Hello IRIS"
            assert msg1["is_final"] is True

            # Receive streamed messages until turn_complete
            received_types = [msg1["type"]]
            while True:
                msg = websocket.receive_json()
                received_types.append(msg["type"])
                if msg["type"] in ("turn_complete", "error"):
                    break

            assert "turn_complete" in received_types or "token_delta" in received_types


def test_websocket_malformed_payload(client):
    """Test sending malformed payload yields structured error message."""
    url = f"/ws?token={auth_manager.master_key}"
    with client.websocket_connect(url) as websocket:
        _ = websocket.receive_json()  # Handshake

        # Send invalid JSON string
        websocket.send_text("Not valid JSON!")
        err1 = websocket.receive_json()
        assert err1["type"] == "error"
        assert err1["code"] == "INVALID_JSON"

        # Send unknown message type
        websocket.send_json({"type": "unsupported_action"})
        err2 = websocket.receive_json()
        assert err2["type"] == "error"
        assert err2["code"] == "INVALID_PROTOCOL"


def test_websocket_binary_frame_handling(client):
    """Test sending binary audio frame over WebSocket."""
    url = f"/ws?token={auth_manager.master_key}"
    with client.websocket_connect(url) as websocket:
        _ = websocket.receive_json()  # Handshake

        # Send raw PCM bytes (0-filled buffer)
        pcm_bytes = bytes([0] * 640)
        websocket.send_bytes(pcm_bytes)

        # Receive VAD event emitted on processing audio chunk
        vad_msg = websocket.receive_json()
        assert vad_msg["type"] == "vad"

        # Connection remains open and healthy for ping/pong
        websocket.send_json({"type": "ping"})
        pong = websocket.receive_json()
        assert pong["type"] == "pong"


@pytest.mark.asyncio
async def test_websocket_disconnect_task_cancellation():
    """Verify manager cleanly cancels active background tasks on disconnect."""
    manager = WebSocketConnectionManager()
    session_id = "test-session-cancel"

    # Simulate a long running task
    async def dummy_long_task():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(dummy_long_task())
    manager.active_tasks[session_id] = {task}

    # Cancel tasks synchronously
    cancelled_count = manager.cancel_tasks_sync(session_id)
    assert cancelled_count == 1
    
    # Yield loop tick for cancellation exception to process
    await asyncio.sleep(0)
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_health_supervisor_websocket_metrics():
    """Verify HealthSupervisor reports active WebSocket connection counts."""
    manager = WebSocketConnectionManager()
    supervisor = health_supervisor
    supervisor.ws_manager = manager

    report = await supervisor.check_fleet()
    assert "active_websocket_connections" in report.details
    assert report.details["active_websocket_connections"] == 0
