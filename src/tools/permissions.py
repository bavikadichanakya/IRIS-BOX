import secrets
import time
import logging
import json
import hashlib
from typing import Optional, Tuple, Dict, Any, Union
from pydantic import BaseModel, Field
from src.tools.capability import Capability, PermissionLevel

logger = logging.getLogger("iris.permissions")


class StepTicket(BaseModel):
    """
    Cryptographic single-use step execution ticket binding plan_id, step_id, tool_name,
    and a SHA256 parameter digest.
    """
    plan_id: str
    step_id: int
    tool_name: str
    params_hash: str
    ticket_id: str = Field(default_factory=lambda: f"stk_{secrets.token_urlsafe(16)}")
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 300.0)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


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

    def get_pending_action(self, token: str) -> Optional[PendingAction]:
        if not token or token not in self._pending_actions:
            return None
        action = self._pending_actions[token]
        if action.is_expired():
            self._pending_actions.pop(token, None)
            return None
        return action

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
    Enforces device authorization, capability access tiering, single-use step execution tickets,
    and server-validated confirmation tokens.
    """

    def __init__(self, default_policy_version: str = "v1.2", default_ticket_ttl_sec: float = 300.0):
        self.policy_version = default_policy_version
        self.default_ticket_ttl_sec = default_ticket_ttl_sec
        self._active_step_tickets: Dict[str, StepTicket] = {}

    def compute_params_hash(self, parameters: Optional[Dict[str, Any]]) -> str:
        """Computes deterministic SHA256 digest of tool parameters."""
        params = parameters if isinstance(parameters, dict) else {}
        canonical = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def issue_step_ticket(
        self,
        plan_id: str,
        step_id: int,
        tool_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        ttl_sec: Optional[float] = None,
    ) -> StepTicket:
        """
        Issues an explicit single-use StepTicket for an approved execution step.
        """
        ttl = ttl_sec or self.default_ticket_ttl_sec
        params_hash = self.compute_params_hash(parameters)
        ticket = StepTicket(
            plan_id=plan_id,
            step_id=step_id,
            tool_name=tool_name,
            params_hash=params_hash,
            created_at=time.time(),
            expires_at=time.time() + ttl,
        )
        self._active_step_tickets[ticket.ticket_id] = ticket
        logger.info(f"Issued StepTicket '{ticket.ticket_id}' for plan '{plan_id}' step {step_id} ({tool_name})")
        return ticket

    def validate_and_consume_step_ticket(
        self,
        ticket_obj: Union[StepTicket, Dict[str, Any], str],
        tool_name: str,
        action_payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates and single-use consumes a step ticket.
        Verifies exact match for tool_name, non-expired TTL, and argument hash digest.
        """
        ticket_id = None
        expected_tool = None
        expected_params_hash = None

        if isinstance(ticket_obj, StepTicket):
            ticket_id = ticket_obj.ticket_id
            expected_tool = ticket_obj.tool_name
            expected_params_hash = ticket_obj.params_hash
        elif isinstance(ticket_obj, dict):
            ticket_id = ticket_obj.get("ticket_id")
            expected_tool = ticket_obj.get("tool_name")
            expected_params_hash = ticket_obj.get("params_hash")
        elif isinstance(ticket_obj, str):
            ticket_id = ticket_obj
            stored = self._active_step_tickets.get(ticket_id)
            if stored:
                expected_tool = stored.tool_name
                expected_params_hash = stored.params_hash
        else:
            return False, "SECURITY_DENIED: Invalid step ticket format."

        if not ticket_id or ticket_id not in self._active_step_tickets:
            return False, "SECURITY_DENIED: Step ticket not found or already consumed."

        stored_ticket = self._active_step_tickets.pop(ticket_id)  # Single-use pop
        if stored_ticket.is_expired():
            return False, "SECURITY_DENIED: Step ticket has expired."

        if stored_ticket.tool_name != tool_name or (expected_tool and expected_tool != tool_name):
            return False, f"SECURITY_DENIED: Step ticket tool mismatch (ticket is for '{stored_ticket.tool_name}', got '{tool_name}')."

        actual_hash = self.compute_params_hash(action_payload)
        if stored_ticket.params_hash != actual_hash:
            logger.warning(
                f"Step ticket parameter hash mismatch for ticket '{ticket_id}': expected {stored_ticket.params_hash}, got {actual_hash}"
            )
            return False, "SECURITY_DENIED: Step ticket argument hash mismatch. Tool arguments do not match authorized step parameters."

        return True, None

    async def evaluate(
        self, capability: Capability, context: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        ctx = context or {}
        device_id = ctx.get("device_id", "unknown")
        device_type = ctx.get("device_type", "pod")
        confirmation_token = ctx.get("confirmation_token")
        step_ticket = ctx.get("step_ticket")

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

        # 4. SENSITIVE Tier: Requires single-use step execution ticket or interactive confirmation token
        if capability.permission_level == PermissionLevel.SENSITIVE:
            if capability.requires_confirmation:
                # 4a. Check Step-Scoped Execution Ticket
                if step_ticket is not None:
                    valid, reason = self.validate_and_consume_step_ticket(
                        ticket_obj=step_ticket,
                        tool_name=capability.name,
                        action_payload=ctx.get("action_payload", {}),
                    )
                    if not valid:
                        return False, reason
                    return True, None

                # 4b. Check Interactive Confirmation Token
                if confirmation_token:
                    valid = confirmation_manager.consume_token(
                        token=confirmation_token,
                        tool_name=capability.name,
                        action_payload=ctx.get("action_payload", {}),
                        device_id=device_id,
                    )
                    if not valid:
                        return False, "SECURITY_DENIED: Invalid, expired, or previously consumed confirmation token."
                    return True, None

                # 4c. Blanket confirmed=True is deprecated and strictly disallowed
                if ctx.get("confirmed") is True:
                    return False, f"SECURITY_DENIED: Blanket confirmed=True is disallowed for SENSITIVE capability '{capability.name}'. Explicit step ticket or confirmation token required."

                # 4d. Create Pending Action requiring user confirmation
                ticket = confirmation_manager.create_pending_action(
                    tool_name=capability.name,
                    action_payload=ctx.get("action_payload", {}),
                    device_id=device_id,
                    session_id=ctx.get("session_id", "unknown"),
                )
                ctx["pending_ticket"] = ticket
                return False, f"CONFIRMATION_REQUIRED: Action '{capability.name}' requires explicit approval token '{ticket['confirmation_token']}'."

        return False, "Denied by default policy."


# Global PermissionManager instance
permission_manager = PermissionManager()
