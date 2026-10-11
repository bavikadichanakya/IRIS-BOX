import os
import time
import pytest
from httpx import AsyncClient, ASGITransport

from src.server.app import app
from src.server.routers.pairing import pairing_manager, PairingSession
from src.server.routers.notifications import broadcaster
from src.security.auth import auth_manager

TEST_MASTER_KEY = os.getenv("IRIS_MASTER_KEY", "iris-master-key-offline-2026")
AUTH_HEADER = {"Authorization": f"Bearer {TEST_MASTER_KEY}"}


@pytest.fixture(autouse=True)
def clean_pairing_state():
    """Ensure clean pairing state before each test."""
    pairing_manager._current_session = None
    pairing_manager._paired_devices.clear()
    auth_manager.device_tokens.clear()
    yield
    pairing_manager._current_session = None
    pairing_manager._paired_devices.clear()
    auth_manager.device_tokens.clear()


# ==========================================
# 1. Pairing Manager Core Logic & Invariants
# ==========================================

def test_pairing_manager_pin_generation():
    session = pairing_manager.generate_pin(ttl_seconds=300)
    assert isinstance(session, PairingSession)
    assert len(session.pin) == 6
    assert session.pin.isdigit()
    assert session.expires_at > time.time()
    assert session.is_expired is False


def test_pairing_manager_single_use_pin():
    session = pairing_manager.generate_pin(ttl_seconds=300)
    pin = session.pin
    
    # First pairing attempt must succeed
    success, token, dev_id = pairing_manager.pair_device(
        pin=pin,
        device_name="Test Phone",
        user_agent="Mozilla/5.0 (iPhone)"
    )
    assert success is True
    assert token.startswith("iris_mob_")
    assert dev_id is not None
    assert token in auth_manager.device_tokens.values()
    assert auth_manager.validate_token(token) is True
    # PIN must be consumed / invalidated
    assert session.invalidated is True
    assert session.is_expired is True

    # Second pairing attempt with same PIN must fail
    success_2, err_msg, _ = pairing_manager.pair_device(pin=pin)
    assert success_2 is False
    assert "expired" in err_msg.lower() or "no active" in err_msg.lower()


def test_pairing_manager_ttl_expiry():
    # Generate session with negative TTL
    session = pairing_manager.generate_pin(ttl_seconds=-1)
    pin = session.pin
    
    success, err_msg, _ = pairing_manager.pair_device(pin=pin)
    assert success is False
    assert "expired" in err_msg.lower() or "no active" in err_msg.lower()


def test_pairing_manager_brute_force_lockout():
    session = pairing_manager.generate_pin(ttl_seconds=300)
    
    # 4 invalid attempts
    for _ in range(4):
        success, msg, _ = pairing_manager.pair_device(pin="999999")
        assert success is False
        assert "attempt(s) remaining" in msg
    
    # 5th invalid attempt triggers lockout
    success, msg, _ = pairing_manager.pair_device(pin="999999")
    assert success is False
    assert "Maximum pairing attempts exceeded" in msg
    assert session.is_expired is True
    assert session.invalidated is True


def test_pairing_manager_device_revocation():
    session = pairing_manager.generate_pin(ttl_seconds=300)
    success, token, dev_id = pairing_manager.pair_device(pin=session.pin)
    assert success is True
    
    assert dev_id in pairing_manager._paired_devices
    assert auth_manager.validate_token(token) is True
    
    # Revoke device
    revoked = pairing_manager.revoke_device(dev_id)
    assert revoked is True
    assert dev_id not in pairing_manager._paired_devices
    assert auth_manager.validate_token(token) is False


# ==========================================
# 2. REST API Integration Endpoints
# ==========================================

@pytest.mark.asyncio
async def test_api_pairing_endpoints_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1: Generate PIN without Auth fails
        unauth_resp = await client.post("/api/pairing/generate", json={})
        assert unauth_resp.status_code in (401, 403)

        # Step 2: Generate PIN with Master Key succeeds
        gen_resp = await client.post("/api/pairing/generate", headers=AUTH_HEADER)
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()
        assert "pin" in gen_data
        assert len(gen_data["pin"]) == 6
        pin = gen_data["pin"]

        # Step 3: Mobile client pairs with PIN (public endpoint)
        pair_resp = await client.post("/api/pairing/pair", json={
            "pin": pin,
            "device_name": "Living Room iPad",
            "user_agent": "TestMobileAgent"
        })
        assert pair_resp.status_code == 200
        pair_data = pair_resp.json()
        assert "device_token" in pair_data
        assert "device_id" in pair_data
        device_token = pair_data["device_token"]
        device_id = pair_data["device_id"]

        # Step 4: Verify device token can access protected endpoints
        auth_mobile_headers = {"Authorization": f"Bearer {device_token}"}
        notif_resp = await client.get("/api/notifications/recent", headers=auth_mobile_headers)
        assert notif_resp.status_code == 200

        # Step 5: Verify device shows up in paired devices list
        devices_resp = await client.get("/api/pairing/devices", headers=AUTH_HEADER)
        assert devices_resp.status_code == 200
        devices = devices_resp.json()["devices"]
        assert any(d["device_id"] == device_id for d in devices)

        # Step 6: Revoke device from Control Center
        revoke_resp = await client.delete(f"/api/pairing/devices/{device_id}", headers=AUTH_HEADER)
        assert revoke_resp.status_code == 200

        # Step 7: Accessing protected endpoints with revoked token fails
        revoked_check = await client.get("/api/notifications/recent", headers=auth_mobile_headers)
        assert revoked_check.status_code in (401, 403)


# ==========================================
# 3. Notification Stream & Event Dispatch
# ==========================================

@pytest.mark.asyncio
async def test_notifications_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Pair a test device
        session = pairing_manager.generate_pin()
        success, token, _ = pairing_manager.pair_device(pin=session.pin)
        assert success is True
        mobile_headers = {"Authorization": f"Bearer {token}"}

        # Dispatch test notification
        test_post = await client.post("/api/notifications/test", json={
            "title": "Smart Home Alert",
            "message": "Front door opened",
            "severity": "WARNING"
        }, headers=AUTH_HEADER)
        assert test_post.status_code == 200

        # Fetch recent notifications
        recent = await client.get("/api/notifications/recent", headers=mobile_headers)
        assert recent.status_code == 200
        items = recent.json()["recent"]
        assert len(items) >= 1
        assert items[0]["message"] == "Front door opened"


# ==========================================
# 4. Air-Gapped PWA Shell & Static Assets
# ==========================================

@pytest.mark.asyncio
async def test_pwa_shell_and_assets_air_gapped():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # /mobile shell
        mobile_resp = await client.get("/mobile")
        assert mobile_resp.status_code == 200
        html = mobile_resp.text
        assert "IRIS Satellite" in html
        assert 'href="/static/mobile/manifest.webmanifest"' in html
        assert 'href="/static/mobile/mobile.css"' in html
        assert 'src="/static/mobile/mobile.js"' in html

        # Zero external CDN / font links
        assert "fonts.googleapis.com" not in html
        assert "fonts.gstatic.com" not in html
        assert "cdn." not in html
        assert "cdnjs." not in html

        # Web Manifest
        manifest_resp = await client.get("/static/mobile/manifest.webmanifest")
        assert manifest_resp.status_code == 200
        manifest = manifest_resp.json()
        assert manifest["display"] == "standalone"
        assert manifest["theme_color"] == "#0B0F19"

        # Service Worker (sw.js)
        sw_resp = await client.get("/static/mobile/sw.js")
        assert sw_resp.status_code == 200
        sw_text = sw_resp.text
        assert "CACHE_NAME" in sw_text
        assert "fonts.googleapis" not in sw_text

        # Icon SVG
        icon_resp = await client.get("/static/mobile/icon.svg")
        assert icon_resp.status_code == 200
        assert "<svg" in icon_resp.text

        # CSS and JS
        css_resp = await client.get("/static/mobile/mobile.css")
        assert css_resp.status_code == 200
        assert "fonts.googleapis" not in css_resp.text

        js_resp = await client.get("/static/mobile/mobile.js")
        assert js_resp.status_code == 200
        assert "AudioContext" in js_resp.text
        assert "EventSource" in js_resp.text
