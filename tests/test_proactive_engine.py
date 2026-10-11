import asyncio
from datetime import time as dtime
import json
import time
from unittest.mock import Mock, patch, AsyncMock
import pytest
import websockets
from starlette.testclient import TestClient

from src.server.app import app
from src.security.auth import auth_manager
from src.config.settings import settings
from src.observability.event_bus import EventBus
from src.automation.ha_listener import HomeAssistantWSClient
from src.automation.dispatcher import ProactiveSpeechDispatcher
from src.automation.proactive_engine import (
    ProactiveEngine,
    ProactiveRule,
    ProactiveAnnouncement,
    get_default_proactive_rules,
)
from src.audio.tts import TTSEngine


# ============================================================================
# 1. HA WebSocket Handshake & Event Subscription Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ha_websocket_handshake_and_subscription_flow():
    """
    Verify HomeAssistantWSClient connects, executes auth handshake, subscribes to
    state_changed events, and emits them on the EventBus.
    """
    event_bus = EventBus()
    received_events = []

    async def _on_ha_event(evt):
        received_events.append(evt.payload)

    event_bus.subscribe("ha.state_changed", _on_ha_event)

    server_received_messages = []
    auth_token = "valid_long_lived_token_123"

    async def mock_ha_server(websocket):
        # 1. Send auth_required
        await websocket.send(json.dumps({"type": "auth_required", "ha_version": "2026.10.0"}))

        # 2. Receive auth
        auth_msg = json.loads(await websocket.recv())
        server_received_messages.append(auth_msg)
        if auth_msg.get("type") == "auth" and auth_msg.get("access_token") == auth_token:
            await websocket.send(json.dumps({"type": "auth_ok", "ha_version": "2026.10.0"}))
        else:
            await websocket.send(json.dumps({"type": "auth_invalid", "message": "Invalid token"}))
            return

        # 3. Receive subscribe_events
        sub_msg = json.loads(await websocket.recv())
        server_received_messages.append(sub_msg)
        await websocket.send(json.dumps({"id": sub_msg["id"], "type": "result", "success": True, "result": None}))

        # 4. Push a state_changed event
        event_payload = {
            "id": sub_msg["id"],
            "type": "event",
            "event": {
                "event_type": "state_changed",
                "data": {
                    "entity_id": "binary_sensor.front_door",
                    "old_state": {"entity_id": "binary_sensor.front_door", "state": "off"},
                    "new_state": {
                        "entity_id": "binary_sensor.front_door",
                        "state": "on",
                        "attributes": {"friendly_name": "Front Door"}
                    }
                }
            }
        }
        await websocket.send(json.dumps(event_payload))

        # Keep open briefly
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

    async with websockets.serve(mock_ha_server, "127.0.0.1", 0) as server:
        # Extract bound port
        host, port = server.sockets[0].getsockname()
        ws_url = f"ws://{host}:{port}/api/websocket"

        client = HomeAssistantWSClient(
            url=ws_url,
            token=auth_token,
            event_bus=event_bus,
            reconnect_interval_min=0.1,
            reconnect_interval_max=1.0,
        )

        await client.start()

        # Allow client to connect, authenticate, subscribe, and receive event
        for _ in range(20):
            if len(received_events) >= 1:
                break
            await asyncio.sleep(0.05)

        assert client.is_connected is True
        assert len(server_received_messages) >= 2
        assert server_received_messages[0]["type"] == "auth"
        assert server_received_messages[1]["type"] == "subscribe_events"
        assert len(received_events) == 1
        assert received_events[0]["entity_id"] == "binary_sensor.front_door"
        assert received_events[0]["new_state"]["state"] == "on"

        # Graceful shutdown
        await client.stop()
        assert client.status == "DISCONNECTED"
        assert client.is_connected is False


# ============================================================================
# 2. Zero-Mock Policy Tests
# ============================================================================

@pytest.mark.asyncio
async def test_zero_mock_policy_disabled_without_credentials():
    """
    Zero-Mock Policy: Missing HA credentials must immediately set status to DISABLED,
    prevent background task startup, and never synthesize fake test events.
    """
    client = HomeAssistantWSClient(token=None)
    assert client.status == "DISABLED"
    assert client.is_connected is False

    await client.start()
    assert client.status == "DISABLED"
    assert client._task is None


# ============================================================================
# 3. State-Change Matching & Template Rendering Tests
# ============================================================================

def test_state_change_matching_and_template_rendering():
    """
    Verify rule evaluation matches entity_id pattern, from/to states,
    and formats human-readable speech template.
    """
    engine = ProactiveEngine()

    # 1. Matching door open event
    door_event = {
        "entity_id": "binary_sensor.front_door",
        "old_state": {"entity_id": "binary_sensor.front_door", "state": "off"},
        "new_state": {
            "entity_id": "binary_sensor.front_door",
            "state": "on",
            "attributes": {"friendly_name": "Front Entry Door"}
        }
    }

    announcement = engine.evaluate_event(door_event, current_time=1000.0)
    assert announcement is not None
    assert announcement.entity_id == "binary_sensor.front_door"
    assert announcement.text == "The Front Entry Door was opened."
    assert announcement.severity == "WARNING"

    # 2. Non-matching entity (light switch)
    light_event = {
        "entity_id": "light.living_room",
        "old_state": {"state": "off"},
        "new_state": {"state": "on", "attributes": {"friendly_name": "Living Room Light"}}
    }
    assert engine.evaluate_event(light_event, current_time=1000.0) is None

    # 3. Ignored transition (already on -> on)
    repeat_on_event = {
        "entity_id": "binary_sensor.back_door",
        "old_state": {"state": "on"},
        "new_state": {"state": "on", "attributes": {"friendly_name": "Back Door"}}
    }
    assert engine.evaluate_event(repeat_on_event, current_time=1000.0) is None


# ============================================================================
# 4. Debounce & Cooldown Enforcement Tests
# ============================================================================

def test_debounce_and_cooldown_enforcement():
    """
    Verify that subsequent triggers for the same entity within cooldown_seconds
    are debounced and suppressed.
    """
    engine = ProactiveEngine()
    event_data = {
        "entity_id": "binary_sensor.garage_door",
        "old_state": {"state": "off"},
        "new_state": {
            "state": "on",
            "attributes": {"friendly_name": "Garage Door"}
        }
    }

    # First trigger at t = 100.0 (cooldown is 60.0s)
    first_ann = engine.evaluate_event(event_data, current_time=100.0)
    assert first_ann is not None
    assert "Garage Door was opened" in first_ann.text

    # Second trigger at t = 120.0 (20s later, within 60s cooldown) -> Must be debounced/suppressed
    second_ann = engine.evaluate_event(event_data, current_time=120.0)
    assert second_ann is None

    # Third trigger at t = 165.0 (65s later, cooldown elapsed) -> Must trigger successfully
    third_ann = engine.evaluate_event(event_data, current_time=165.0)
    assert third_ann is not None


# ============================================================================
# 5. Quiet Hours & Severity Override Tests
# ============================================================================

def test_quiet_hours_and_critical_severity_override():
    """
    Verify quiet hours computation, suppression of INFO/WARNING alerts during quiet hours,
    and guarantee that CRITICAL alerts (leak/fire) bypass quiet hours unconditionally.
    """
    engine = ProactiveEngine()

    # Test is_in_quiet_hours logic (default quiet hours 23:00 to 07:00)
    assert engine.is_in_quiet_hours(dtime(23, 30)) is True
    assert engine.is_in_quiet_hours(dtime(3, 0)) is True
    assert engine.is_in_quiet_hours(dtime(6, 59)) is True
    assert engine.is_in_quiet_hours(dtime(7, 0)) is False
    assert engine.is_in_quiet_hours(dtime(14, 30)) is False
    assert engine.is_in_quiet_hours(dtime(22, 59)) is False

    # During daytime (14:00): Motion (INFO) triggers
    motion_event = {
        "entity_id": "binary_sensor.hallway_motion",
        "old_state": {"state": "off"},
        "new_state": {"state": "on", "attributes": {"friendly_name": "Hallway Motion"}}
    }
    day_ann = engine.evaluate_event(motion_event, current_time=100.0, test_quiet_time=dtime(14, 0))
    assert day_ann is not None

    # During quiet hours (02:00): Motion (INFO) is MUTED
    night_motion_ann = engine.evaluate_event(motion_event, current_time=2000.0, test_quiet_time=dtime(2, 0))
    assert night_motion_ann is None

    # During quiet hours (02:00): Water Leak (CRITICAL) BYPASSES quiet hours
    leak_event = {
        "entity_id": "binary_sensor.basement_leak",
        "old_state": {"state": "off"},
        "new_state": {"state": "on", "attributes": {"friendly_name": "Basement Water Sensor"}}
    }
    leak_ann = engine.evaluate_event(leak_event, current_time=2000.0, test_quiet_time=dtime(2, 0))
    assert leak_ann is not None
    assert leak_ann.severity == "CRITICAL"
    assert "Critical alert" in leak_ann.text


# ============================================================================
# 6. Proactive Speech Synthesis & WebSocket Broadcast Tests
# ============================================================================

@pytest.mark.asyncio
async def test_proactive_speech_dispatcher_broadcast():
    """
    Verify ProactiveSpeechDispatcher generates speech audio via TTSEngine,
    and broadcasts the JSON envelope and binary audio to active WebSocket connections.
    """
    mock_tts = Mock(spec=TTSEngine)
    mock_tts.synthesize = AsyncMock(return_value=b"RIFF_FAKE_WAV_BYTES_DATA")

    mock_ws = Mock()
    mock_ws.send_text = AsyncMock()
    mock_ws.send_bytes = AsyncMock()

    conn_mgr = Mock()
    conn_mgr.active_connections = {"session_sat_1": mock_ws}
    conn_mgr.disconnect = AsyncMock()

    dispatcher = ProactiveSpeechDispatcher(
        tts_engine=mock_tts,
        connection_manager=conn_mgr,
        play_physical_speaker=False,
    )

    res = await dispatcher.dispatch(
        text="The front door was left open.",
        severity="WARNING",
        entity_id="binary_sensor.front_door",
        timestamp=1791628833.0,
    )

    assert res["status"] == "DISPATCHED"
    assert res["satellites_notified"] == 1
    assert res["audio_bytes"] == len(b"RIFF_FAKE_WAV_BYTES_DATA")

    # Verify TTS called
    mock_tts.synthesize.assert_awaited_once_with("The front door was left open.")

    # Verify WS envelope sent
    mock_ws.send_text.assert_awaited_once()
    sent_text = mock_ws.send_text.call_args[0][0]
    envelope = json.loads(sent_text)
    assert envelope["type"] == "proactive_announcement"
    assert envelope["text"] == "The front door was left open."
    assert envelope["severity"] == "WARNING"

    # Verify binary audio sent
    mock_ws.send_bytes.assert_awaited_once_with(b"RIFF_FAKE_WAV_BYTES_DATA")


# ============================================================================
# 7. REST Management Endpoints & Dashboard Status Tests
# ============================================================================

def test_proactive_automation_rest_api_and_dashboard():
    """
    Verify security boundaries (HTTP 401 unauthenticated), REST rule inspection,
    manual announcement test triggering, and Control Center Dashboard status card.
    """
    app.state.proactive_engine = ProactiveEngine()
    app.state.ha_client = HomeAssistantWSClient(token=None)
    client = TestClient(app)
    auth_headers = {"X-API-Key": auth_manager.master_key}


    # 1. Unauthenticated Security Boundary -> HTTP 401
    res_unauth_rules = client.get("/api/automation/proactive/rules")
    assert res_unauth_rules.status_code == 401

    res_unauth_test = client.post("/api/automation/proactive/test", json={"text": "Test speech"})
    assert res_unauth_test.status_code == 401

    # 2. Authenticated: List rules
    res_rules = client.get("/api/automation/proactive/rules", headers=auth_headers)
    assert res_rules.status_code == 200
    data_rules = res_rules.json()
    assert data_rules["count"] >= 3
    rule_patterns = [r["entity_id_pattern"] for r in data_rules["rules"]]
    assert any("door" in p for p in rule_patterns)

    # 3. Authenticated: Manual test speech announcement
    res_test = client.post(
        "/api/automation/proactive/test",
        headers=auth_headers,
        json={"text": "Manual ambient announcement test", "severity": "INFO"},
    )
    assert res_test.status_code == 200
    data_test = res_test.json()
    assert data_test["status"] == "triggered"
    assert data_test["result"]["status"] == "DISPATCHED"

    # 4. Authenticated: Engine status
    res_status = client.get("/api/automation/proactive/status", headers=auth_headers)
    assert res_status.status_code == 200
    data_status = res_status.json()
    assert "ha_connection_status" in data_status
    assert "active_rules_count" in data_status
    assert "is_quiet_hours" in data_status

    # 5. Dashboard integration: check proactive_engine subsystem matrix card
    res_dash = client.get("/api/dashboard/status")
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    subsystems = dash_data.get("subsystems", {})
    assert "proactive_engine" in subsystems
    proactive_card = subsystems["proactive_engine"]
    assert proactive_card["name"] == "Ambient Proactive Engine"
    assert "connection_status" in proactive_card
    assert "active_rules_count" in proactive_card
