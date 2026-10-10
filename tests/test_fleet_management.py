import time
import asyncio
import pytest
from fastapi.testclient import TestClient

from src.server.app import app
from src.server.fleet import FleetManager, SpeakerDevice, CommandResult, FleetBroadcastResult
from src.server.websocket import WebSocketConnectionManager
from src.observability.event_bus import EventBus


@pytest.fixture
def fleet_mgr():
    bus = EventBus()
    ws_mgr = WebSocketConnectionManager(event_bus=bus)
    fm = FleetManager(heartbeat_timeout_seconds=0.1, ws_manager=ws_mgr, event_bus=bus)
    return fm


@pytest.mark.asyncio
async def test_device_registration_and_token_authentication(fleet_mgr):
    """Test device registration, capability assignment, and token hashing authentication."""
    dev = fleet_mgr.register_speaker(
        speaker_id="dev-auth-01",
        name="Living Room Display",
        room="Living Room",
        device_type="display",
        capabilities=["audio_out", "screen"],
        auth_token="secret-token-123"
    )

    assert dev.speaker_id == "dev-auth-01"
    assert dev.device_id == "dev-auth-01"
    assert dev.room == "living room"
    assert dev.device_type == "display"
    assert "audio_out" in dev.capabilities

    # Test authentication logic
    assert fleet_mgr.authenticate_device("dev-auth-01", "secret-token-123") is True
    assert fleet_mgr.authenticate_device("dev-auth-01", "wrong-token") is False
    assert fleet_mgr.authenticate_device("non-existent-dev", "secret-token-123") is False


@pytest.mark.asyncio
async def test_heartbeat_expiry_sweeping(fleet_mgr):
    """Test heartbeat recording and stale device sweeping transitioning status to OFFLINE."""
    bus_events = []

    async def event_handler(event):
        bus_events.append(event)

    fleet_mgr.event_bus.subscribe("fleet.device.offline", event_handler)

    dev = fleet_mgr.register_speaker("dev-hb-01", "Kitchen Speaker", "kitchen")
    assert dev.status == "online"

    # Simulate heartbeat timeout
    dev.last_heartbeat = time.time() - 1.0

    stale = fleet_mgr.sweep_stale_devices(timeout_seconds=0.1)
    assert "dev-hb-01" in stale
    assert dev.status == "offline"

    # Give event bus time to process event loop task
    await asyncio.sleep(0.05)
    assert any(e.payload["device_id"] == "dev-hb-01" for e in bus_events)


@pytest.mark.asyncio
async def test_command_dispatch_with_ack(fleet_mgr):
    """Test sending command over active WebSocket connection with successful client ACK."""
    dev_id = "ws-dev-01"
    sess_id = "sess-01"

    fleet_mgr.register_speaker(dev_id, "Smart Hub", "Office")

    # Mock active WebSocket connection in ws_manager
    class FakeWebSocket:
        def __init__(self):
            self.sent_messages = []

        async def send_json(self, data):
            self.sent_messages.append(data)

    fake_ws = FakeWebSocket()
    await fleet_mgr.ws_manager.connect(fake_ws, device_id=dev_id, session_id=sess_id)

    # Dispatch command in background
    cmd_task = asyncio.create_task(
        fleet_mgr.send_command(dev_id, command_type="set_volume", payload={"level": 75}, timeout=1.0)
    )

    await asyncio.sleep(0.05)
    assert len(fake_ws.sent_messages) == 1
    msg = fake_ws.sent_messages[0]
    assert msg["type"] == "device_command"
    assert msg["action"] == "set_volume"
    cmd_id = msg["command_id"]

    # Simulate client sending ACK
    from src.server.protocol import InboundCommandAckPayload
    fleet_mgr.handle_command_ack(
        InboundCommandAckPayload(command_id=cmd_id, status="OK", output={"volume": 75})
    )

    res: CommandResult = await cmd_task
    assert res.delivered is True
    assert res.acknowledged is True
    assert res.output == {"volume": 75}
    assert res.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_command_timeout_and_offline_handling(fleet_mgr):
    """Test command handling when device is offline or unacknowledged."""
    # 1. Device offline
    fleet_mgr.register_speaker("off-dev", "Offline Speaker", "garage")
    fleet_mgr.get_speaker("off-dev").status = "offline"

    res_off = await fleet_mgr.send_command("off-dev", "reboot")
    assert res_off.delivered is False
    assert res_off.acknowledged is False
    assert "offline" in res_off.error.lower()

    # 2. Device connected but fails to send ACK (timeout)
    dev_id = "timeout-dev"
    sess_id = "sess-timeout"
    fleet_mgr.register_speaker(dev_id, "Timeout Speaker", "patio")

    class SilentWebSocket:
        async def send_json(self, data):
            pass

    await fleet_mgr.ws_manager.connect(SilentWebSocket(), device_id=dev_id, session_id=sess_id)

    res_timeout = await fleet_mgr.send_command(dev_id, "update_firmware", timeout=0.1)
    assert res_timeout.delivered is True
    assert res_timeout.acknowledged is False
    assert "timed out" in res_timeout.error.lower()


@pytest.mark.asyncio
async def test_room_broadcasting_with_partial_failures(fleet_mgr):
    """Test room-based broadcasting reporting accurate targeted, sent, acknowledged, and failed counts."""
    # Setup 3 devices in bedroom
    fleet_mgr.register_speaker("bed-1", "Bed 1", "bedroom")
    fleet_mgr.register_speaker("bed-2", "Bed 2", "bedroom")
    fleet_mgr.register_speaker("bed-3", "Bed 3", "bedroom")

    # Connect bed-1 (will ACK) and bed-2 (will timeout/fail). Leave bed-3 disconnected.
    class InteractiveWS:
        def __init__(self, should_ack: bool):
            self.should_ack = should_ack

        async def send_json(self, data):
            if self.should_ack and data.get("type") == "device_command":
                cmd_id = data["command_id"]
                from src.server.protocol import InboundCommandAckPayload
                # Send ACK asynchronously
                asyncio.get_running_loop().call_soon(
                    fleet_mgr.handle_command_ack,
                    InboundCommandAckPayload(command_id=cmd_id, status="OK")
                )

    await fleet_mgr.ws_manager.connect(InteractiveWS(should_ack=True), device_id="bed-1", session_id="sess-bed-1")
    await fleet_mgr.ws_manager.connect(InteractiveWS(should_ack=False), device_id="bed-2", session_id="sess-bed-2")

    broadcast_res: FleetBroadcastResult = await fleet_mgr.broadcast_command(
        command="mute",
        room="bedroom",
        timeout=0.1
    )

    assert broadcast_res.target_count == 3
    assert broadcast_res.sent_count == 2
    assert broadcast_res.acknowledged_count == 1
    assert "bed-2" in broadcast_res.failed_devices
    assert "bed-3" in broadcast_res.failed_devices
    assert broadcast_res.delivered is True


def test_fleet_http_endpoints():
    """Test HTTP fleet API endpoints (/api/fleet/... and /fleet/...)."""
    from src.security.auth import auth_manager
    with TestClient(app, headers={"Authorization": f"Bearer {auth_manager.master_key}"}) as client:
        # 1. Register device via POST /api/fleet/devices/register
        reg_payload = {
            "speaker_id": "http-dev-01",
            "name": "Kitchen Display",
            "room": "kitchen",
            "device_type": "display",
            "capabilities": ["screen", "touch"],
            "auth_token": "secret-123"
        }
        res_reg = client.post("/api/fleet/devices/register", json=reg_payload)
        assert res_reg.status_code == 200
        data_reg = res_reg.json()
        assert data_reg["speaker_id"] == "http-dev-01"
        assert data_reg["device_type"] == "display"

        # 2. List devices via GET /api/fleet/devices
        res_list = client.get("/api/fleet/devices")
        assert res_list.status_code == 200
        devices = res_list.json()
        assert any(d["speaker_id"] == "http-dev-01" for d in devices)

        # 3. Send broadcast via POST /api/fleet/commands
        cmd_payload = {
            "command": "night_mode",
            "room": "kitchen",
            "payload": {"brightness": 10}
        }
        res_cmd = client.post("/api/fleet/commands", json=cmd_payload)
        assert res_cmd.status_code == 200
        bc_data = res_cmd.json()
        assert bc_data["command"] == "night_mode"
        assert "http-dev-01" in bc_data["target_speaker_ids"]
