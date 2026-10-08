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
        fm =