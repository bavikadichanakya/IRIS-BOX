import time
import pytest
from fastapi.testclient import TestClient

from src.server.app import app
from src.server.fleet import FleetManager


class TestFleetManagerUnit:
    def test_register_and_get_speaker(self):
        fm = FleetManager()
        spk = fm.register_speaker("spk-1", "Kitchen Echo", "Kitchen", "192.168.1.10")
        assert spk.speaker_id == "spk-1"
        assert spk.name == "Kitchen Echo"
        assert spk.room == "kitchen"
        assert spk.ip_address == "192.168.1.10"
        assert spk.status == "online"

        retrieved = fm.get_speaker("spk-1")
        assert retrieved is not None
        assert retrieved.name == "Kitchen Echo"

    def test_unregister_speaker(self):
        fm = FleetManager()
        fm.register_speaker("spk-1", "Kitchen Echo", "Kitchen")
        assert fm.unregister_speaker("spk-1") is True
        assert fm.unregister_speaker("spk-1") is False
        assert fm.get_speaker("spk-1") is None

    def test_heartbeat_updates_timestamp_and_status(self):
        fm = FleetManager()
        spk = fm.register_speaker("spk-1", "Living Room Speaker", "living room")
        old_time = spk.last_heartbeat

        time.sleep(0.01)
        updated = fm.record_heartbeat("spk-1", status="busy")
        assert updated.last_heartbeat >= old_time
        assert updated.status == "busy"

    def test_record_heartbeat_unknown_speaker_raises(self):
        fm = FleetManager()
        with pytest.raises(KeyError):
            fm.record_heartbeat("unknown-id")

    def test_room_grouping_and_list_rooms(self):
        fm = FleetManager()
        fm.register_speaker("spk-1", "Kitchen 1", "kitchen")
        fm.register_speaker("spk-2", "Kitchen 2", "Kitchen")
        fm.register_speaker("spk-3", "Bedroom 1", "bedroom")

        rooms = fm.list_rooms()
        assert rooms == ["bedroom", "kitchen"]

        by_room = fm.get_speakers_by_room()
        assert len(by_room["kitchen"]) == 2
        assert len(by_room["bedroom"]) == 1

        kitchen_speakers = fm.list_speakers(room="kitchen")
        assert len(kitchen_speakers) == 2

    def test_check_stale_speakers(self):
        fm = FleetManager(heartbeat_timeout_seconds=0.05)
        spk = fm.register_speaker("spk-1", "Stale Device", "office")
        spk.last_heartbeat = time.time() - 0.1

        stale = fm.check_stale_speakers()
        assert "spk-1" in stale
        assert fm.get_speaker("spk-1").status == "offline"

        active = fm.list_speakers(active_only=True)
        assert len(active) == 0

    def test_broadcast_commands(self):
        fm = FleetManager()
        fm.register_speaker("spk-1", "Kitchen 1", "kitchen")
        fm.register_speaker("spk-2", "Bedroom 1", "bedroom")
        fm.register_speaker("spk-3", "Bedroom 2", "bedroom")

        # Global broadcast
        res_all = fm.broadcast(command="play_chime")
        assert res_all.target_count == 3
        assert set(res_all.target_speaker_ids) == {"spk-1", "spk-2", "spk-3"}

        # Room broadcast
        res_room = fm.broadcast(command="mute", room="bedroom")
        assert res_room.target_count == 2
        assert set(res_room.target_speaker_ids) == {"spk-2", "spk-3"}

        # Explicit target broadcast
        res_specific = fm.broadcast(command="reboot", speaker_ids=["spk-1"])
        assert res_specific.target_count == 1
        assert res_specific.target_speaker_ids == ["spk-1"]


class TestFleetRoutes:
    @pytest.fixture
    def client(self):
        with TestClient(app, headers={"Authorization": "Bearer ollama"}) as test_client:
            yield test_client

    def test_register_speaker_route(self, client):
        payload = {
            "speaker_id": "route-spk-1",
            "name": "Dining Room Echo",
            "room": "Dining Room",
            "ip_address": "192.168.1.50",
            "metadata": {"volume": 80}
        }
        res = client.post("/fleet/register", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["speaker_id"] == "route-spk-1"
        assert data["room"] == "dining room"
        assert data["status"] == "online"
        assert data["metadata"]["volume"] == 80

    def test_get_speaker_and_list_speakers_route(self, client):
        client.post("/fleet/register", json={
            "speaker_id": "r-spk-2",
            "name": "Hallway Dot",
            "room": "hallway"
        })

        get_res = client.get("/fleet/speakers/r-spk-2")
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "Hallway Dot"

        not_found = client.get("/fleet/speakers/non-existent")
        assert not_found.status_code == 404

        list_res = client.get("/fleet/speakers?room=hallway")
        assert list_res.status_code == 200
        assert any(s["speaker_id"] == "r-spk-2" for s in list_res.json())

    def test_heartbeat_route(self, client):
        client.post("/fleet/register", json={
            "speaker_id": "hb-spk",
            "name": "Patio Speaker",
            "room": "patio"
        })

        res = client.post("/fleet/heartbeat", json={"speaker_id": "hb-spk", "status": "busy"})
        assert res.status_code == 200
        assert res.json()["status"] == "busy"

        res_404 = client.post("/fleet/heartbeat", json={"speaker_id": "unknown-hb"})
        assert res_404.status_code == 404

    def test_rooms_route(self, client):
        client.post("/fleet/register", json={
            "speaker_id": "room-spk-1",
            "name": "Garage Speaker",
            "room": "garage"
        })
        res = client.get("/fleet/rooms")
        assert res.status_code == 200
        data = res.json()
        assert "garage" in data["rooms"]
        assert "garage" in data["by_room"]

    def test_broadcast_route(self, client):
        client.post("/fleet/register", json={
            "speaker_id": "bc-spk-1",
            "name": "Lounge Speaker",
            "room": "lounge"
        })

        res = client.post("/fleet/broadcast", json={
            "command": "announce",
            "room": "lounge",
            "payload": {"message": "Dinner is ready"}
        })
        assert res.status_code == 200
        data = res.json()
        assert data["command"] == "announce"
        assert "bc-spk-1" in data["target_speaker_ids"]
        assert data["delivered"] is True

    def test_delete_speaker_route(self, client):
        client.post("/fleet/register", json={
            "speaker_id": "del-spk",
            "name": "Guest Room",
            "room": "guest"
        })

        del_res = client.delete("/fleet/speakers/del-spk")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "unregistered"

        del_res_again = client.delete("/fleet/speakers/del-spk")
        assert del_res_again.status_code == 404
