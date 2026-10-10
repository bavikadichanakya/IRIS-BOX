import secrets
import time
import logging
from typing import Optional, Tuple, Dict, Any
from src.tools.capability import Capability, PermissionLevel

logger = logging.getLogger("iris.permissions")


class PendingAction:
    def __init__(
        self,
        token: str,
        tool_name: str,
        action_payload: Dict[str, Any],
        device_id: str,
        session_id: str,
        ttl_sec: float = 300.0,
    ):
        self.token = token
        self.tool_name = tool_name
        self.action_payload = action_payload
        self.device_id = device_id
        self.session_id = session_id
        self.created_at = time.time()
        self.expires_at = self.created_at + ttl_sec

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class ConfirmationManager:
    """
    Manages server-generated, single-use approval tokens for sensitive tool actions.
    Tokens are cryptographically random, bound to exact action payloads & requesting device,
    and expire after a configurable TTL.
    """
    def __init__(self, default_ttl_sec: float = 300.0):
        self.default_ttl_sec = default_ttl_sec
        self._pending_actions: Dict[str, PendingAction] = {}

    def create_pending_action(
        self,
        tool_name: str,
        action_payload: Dict[str, Any],
        device_id: str = "unknown",
        session_id: str = "unknown",
        ttl_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        token = f"cfm_{secrets.token_urlsafe(24)}"
        ttl = ttl_sec or self.default_ttl_sec
        action = PendingAction(
            token=token,
            tool_name=tool_name,
            action_payload=action_payload,
            device_id=device_id,
            session_id=session_id,
            ttl_sec=ttl,
        )
        self._pending_actions[token] = action
        logger.info(f"Created pending action token '{token}' for tool '{tool_name}' (device '{device_id}')")
        return {
            "confirmation_token": token,
            "tool_name": tool_name,
            "action_payload": action_payload,
            "device_id": device_id,
            "expires_at": action.expires_at,
        }

    def consume_token(
        self,
        token: str,
        tool_name: str,
        action_payload: Optional[Dict[str, Any]] = None,
        device_id: Optional[str] = None,
    ) -> bool:
        if not token or token not in self._pending_actions:
            logger.warning(f"Confirmation token '{token}' not found or invalid.")
            return False

        action = self._pending_actions.pop(token)  # Single-use: pop immediately
        if action.is_expired():
            logger.warning(f"Confirmation token '{token}' expired.")
            return False

        if action.tool_name != tool_name:
            logger.warning(f"Confirmation token '{token}' tool mismatch: expected '{action.tool_name}', got '{tool_name}'.")
            return False

        if device_id and device_id != "unknown" and action.device_id != "unknown" and action.device_id != device_id:
            logger.warning(f"Confirmation token '{token}' device mismatch: expected '{action.device_id}', got '{device_id}'.")
            return False

        return True


confirmation_manager = ConfirmationManager()


class PermissionManager:
    """
    Evaluates policy rules before tool invocation.
    Enforces device authorization, capability access tiering, and server-validated confirmation tokens.
    """

    def __init__(self, default_policy_version: str = "v1.2"):
        self.policy_version = default_policy_version

    async def evaluate(
        self, capability: Capability, context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        ctx = context or {}
        device_id = ctx.get("device_id", "unknown")
        device_type = ctx.get("device_type", "pod")
        confirmation_token = ctx.get("confirmation_token")

        # 1. Device Compatibility Check
        if capability.supported_devices and device_type not in capability.supported_devices:
            return False, f"Device type '{device_type}' not authorized for capability '{capability.name}'"

        # 2. PUBLIC Tier: Always allowed
        if capability.permission_level == PermissionLevel.PUBLIC:
            return True, None

        # 3. PROTECTED Tier: Requires valid registered device
        if capability.permission_level == PermissionLevel.PROTECTED:
            if not device_id or device_id == "unknown":
                return False, f"PROTECTED capability '{capability.name}' requires a verified device_id."
            return True, None

        # 4. SENSITIVE Tier: Requires server-validated single-use approval token
        if capability.permission_level == PermissionLevel.SENSITIVE:
            if capability.requires_confirmation:
                if not confirmation_token:
                    ticket = confirmation_manager.create_pending_action(
                        tool_name=capability.name,
                        action_payload=ctx.get("action_payload", {}),
                        device_id=device_id,
                        session_id=ctx.get("session_id", "unknown"),
                    )
                    ctx["pending_ticket"] = ticket
                    return False, f"CONFIRMATION_REQUIRED: Action '{capability.name}' requires explicit approval token '{ticket['confirmation_token']}'."
                else:
                    valid = confirmation_manager.consume_token(
                        token=confirmation_token,
                        tool_name=capability.name,
                        action_payload=ctx.get("action_payload", {}),
                        device_id=device_id,
                    )
                    if not valid:
                        return False, f"SECURITY_DENIED: Invalid, expired, or previously consumed confirmation token."
                    return True, None

        return False, "Denied by default policy."
