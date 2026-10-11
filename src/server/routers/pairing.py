import logging
import secrets
import time
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request, status, Depends
from pydantic import BaseModel, Field

from src.security.auth import auth_manager, verify_api_key
from src.observability.event_bus import EventBus

logger = logging.getLogger("iris.server.routers.pairing")

router = APIRouter(prefix="/pairing", tags=["LAN Device Pairing"])


class PairingSession:
    def __init__(self, pin: str, ttl_seconds: int = 300, max_attempts: int = 5):
        self.pin = pin
        self.created_at = time.time()
        self.expires_at = self.created_at + ttl_seconds
        self.attempts = 0
        self.max_attempts = max_attempts
        self.invalidated = False

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at or self.invalidated or self.attempts >= self.max_attempts


class PairingManager:
    """
    Manages LAN pairing pin lifecycles, brute-force mitigation, and scoped device tokens.
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or EventBus()
        self._current_session: Optional[PairingSession] = None
        self._paired_devices: Dict[str, Dict] = {}  # device_id -> metadata

    def generate_pin(self, ttl_seconds: int = 300) -> PairingSession:
        """Generate a single-use 6-digit numeric PIN with a 5-minute TTL."""
        pin = f"{secrets.randbelow(1000000):06d}"
        session = PairingSession(pin=pin, ttl_seconds=ttl_seconds, max_attempts=5)
        self._current_session = session
        logger.info("Generated LAN pairing PIN with %ds TTL.", ttl_seconds)
        return session

    def get_current_session(self) -> Optional[PairingSession]:
        if self._current_session and not self._current_session.is_expired:
            return self._current_session
        return None

    def pair_device(
        self,
        pin: str,
        device_id: Optional[str] = None,
        device_name: str = "Mobile Companion",
        user_agent: str = "unknown"
    ) -> tuple[bool, str, Optional[str]]:
        """
        Validate PIN against the active pairing session.
        Returns: (success, message_or_token, resolved_device_id)
        """
        if not self._current_session or self._current_session.is_expired:
            return False, "No active pairing session or PIN has expired.", None

        session = self._current_session

        # Brute-force check
        if session.attempts >= session.max_attempts:
            session.invalidated = True
            return False, "Maximum pairing attempts exceeded. Please generate a new PIN.", None

        if not secrets.compare_digest(pin.strip(), session.pin):
            session.attempts += 1
            remaining = session.max_attempts - session.attempts
            if remaining <= 0:
                session.invalidated = True
                return False, "Maximum pairing attempts exceeded. PIN invalidated.", None
            return False, f"Invalid pairing PIN. {remaining} attempt(s) remaining.", None

        # Successful match - invalidate PIN (single-use invariant)
        session.invalidated = True
        dev_id = device_id.strip() if device_id else f"mob_{secrets.token_hex(6)}"
        device_token = f"iris_mob_{secrets.token_hex(24)}"

        # Register scoped token in AuthManager
        auth_manager.register_device_token(dev_id, device_token)

        meta = {
            "device_id": dev_id,
            "device_name": device_name,
            "device_type": "mobile",
            "user_agent": user_agent,
            "paired_at": time.time(),
        }
        self._paired_devices[dev_id] = meta

        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.event_bus.publish("device.paired", meta))
            except RuntimeError:
                pass
        except Exception:
            pass

        logger.info("Successfully paired mobile device '%s' (%s).", dev_id, device_name)
        return True, device_token, dev_id

    def list_devices(self) -> List[Dict]:
        return list(self._paired_devices.values())

    def revoke_device(self, device_id: str) -> bool:
        auth_manager.revoke_device_token(device_id)
        removed = self._paired_devices.pop(device_id, None)
        if removed:
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.event_bus.publish("device.revoked", {"device_id": device_id}))
                except RuntimeError:
                    pass
            except Exception:
                pass
            logger.info("Revoked pairing for device '%s'.", device_id)
            return True
        return False


# Singleton PairingManager
pairing_manager = PairingManager()


class PairRequestPayload(BaseModel):
    pin: str = Field(..., min_length=6, max_length=6, description="6-digit numeric pairing PIN")
    device_id: Optional[str] = Field(None, description="Client-generated unique device identifier")
    device_name: Optional[str] = Field("Mobile Companion", description="Friendly device label")
    user_agent: Optional[str] = Field("Mobile Browser", description="Client user agent")


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate_pairing_pin():
    """
    Generate an ephemeral 6-digit pairing PIN with a 5-minute TTL.
    Requires master key or admin privileges.
    """
    session = pairing_manager.generate_pin(ttl_seconds=300)
    qr_payload = f"iris://pair?pin={session.pin}"
    return {
        "success": True,
        "pin": session.pin,
        "expires_at": session.expires_at,
        "ttl_seconds": 300,
        "qr_payload": qr_payload,
    }


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def get_pairing_status():
    """Check whether an active pairing session is available."""
    session = pairing_manager.get_current_session()
    if not session:
        return {"active": False, "pin": None, "ttl_remaining": 0}
    remaining = max(0, int(session.expires_at - time.time()))
    return {
        "active": True,
        "pin": session.pin,
        "ttl_remaining": remaining,
        "attempts": session.attempts,
    }


@router.post("/pair")
async def pair_mobile_client(payload: PairRequestPayload):
    """
    Public / LAN pairing endpoint: exchanges valid 6-digit PIN for a scoped device token.
    Enforces 5-minute TTL and brute-force lockout after repeated failed attempts.
    """
    success, token_or_msg, dev_id = pairing_manager.pair_device(
        pin=payload.pin,
        device_id=payload.device_id,
        device_name=payload.device_name or "Mobile Companion",
        user_agent=payload.user_agent or "Mobile PWA"
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=token_or_msg
        )

    return {
        "success": True,
        "device_id": dev_id,
        "token": token_or_msg,
        "device_token": token_or_msg,
        "token_type": "Bearer",
        "message": "Device paired successfully."
    }


@router.get("/devices", dependencies=[Depends(verify_api_key)])
async def list_paired_devices():
    """List all currently paired handheld/mobile devices."""
    return {"devices": pairing_manager.list_devices()}


@router.delete("/devices/{device_id}", dependencies=[Depends(verify_api_key)])
async def revoke_paired_device(device_id: str):
    """Instantly revoke a device token and deregister the paired mobile device."""
    revoked = pairing_manager.revoke_device(device_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device '{device_id}' not found among paired devices."
        )
    return {"success": True, "device_id": device_id, "message": "Device pairing revoked."}
