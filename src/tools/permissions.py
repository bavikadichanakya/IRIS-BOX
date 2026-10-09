import logging
from typing import Optional, Tuple, Dict, Any
from src.tools.capability import Capability, PermissionLevel

logger = logging.getLogger("iris.permissions")

class PermissionManager:
    """
    Evaluates policy rules before tool invocation.
    Enforces device authorization, capability access tiering, and confirmation requirements.
    """

    def __init__(self, default_policy_version: str = "v1.2"):
        self.policy_version = default_policy_version

    async def evaluate(
        self, capability: Capability, context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        ctx = context or {}
        device_id = ctx.get("device_id", "unknown")
        device_type = ctx.get("device_type", "pod")
        confirmed = ctx.get("confirmed", False)

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

        # 4. SENSITIVE Tier: Requires explicit confirmation token
        if capability.permission_level == PermissionLevel.SENSITIVE:
            if capability.requires_confirmation and not confirmed:
                return False, f"CONFIRMATION_REQUIRED: Action '{capability.name}' requires explicit confirmation."
            return True, None

        return False, "Denied by default policy."
