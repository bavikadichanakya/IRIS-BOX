import pytest
from src.tools.capability import Capability, PermissionLevel
from src.tools.permissions import PermissionManager, confirmation_manager

@pytest.mark.asyncio
async def test_public_capability_allowed():
    pm = PermissionManager()
    cap = Capability(
        name="GetTimeTool",
        description="Get current time",
        permission_level=PermissionLevel.PUBLIC
    )
    allowed, reason = await pm.evaluate(cap, context={})
    assert allowed is True
    assert reason is None

@pytest.mark.asyncio
async def test_protected_capability_denied_without_device_id():
    pm = PermissionManager()
    cap = Capability(
        name="HomeAssistantTool",
        description="Toggle home assistant devices",
        permission_level=PermissionLevel.PROTECTED
    )
    allowed, reason = await pm.evaluate(cap, context={"device_id": ""})
    assert allowed is False
    assert "requires a verified device_id" in reason

@pytest.mark.asyncio
async def test_protected_capability_allowed_with_device_id():
    pm = PermissionManager()
    cap = Capability(
        name="HomeAssistantTool",
        description="Toggle home assistant devices",
        permission_level=PermissionLevel.PROTECTED
    )
    allowed, reason = await pm.evaluate(cap, context={"device_id": "pod-kitchen-01", "device_type": "pod"})
    assert allowed is True
    assert reason is None

@pytest.mark.asyncio
async def test_sensitive_capability_requires_confirmation():
    pm = PermissionManager()
    cap = Capability(
        name="SystemCommandTool",
        description="Execute shell commands",
        permission_level=PermissionLevel.SENSITIVE,
        requires_confirmation=True
    )
    ctx = {"device_id": "laptop-01", "action_payload": {"cmd": "ls"}}
    # Without confirmation token (creates pending action)
    allowed, reason = await pm.evaluate(cap, context=ctx)
    assert allowed is False
    assert "CONFIRMATION_REQUIRED" in reason
    token = ctx.get("pending_ticket", {}).get("confirmation_token")
    assert token is not None

    # With valid confirmation token
    ctx_confirmed = {
        "device_id": "laptop-01",
        "action_payload": {"cmd": "ls"},
        "confirmation_token": token
    }
    allowed, reason = await pm.evaluate(cap, context=ctx_confirmed)
    assert allowed is True
    assert reason is None

@pytest.mark.asyncio
async def test_device_type_restriction():
    pm = PermissionManager()
    cap = Capability(
        name="PodOnlyTool",
        description="Only for pod",
        supported_devices=["pod"]
    )
    allowed, reason = await pm.evaluate(cap, context={"device_id": "phone-01", "device_type": "phone"})
    assert allowed is False
    assert "not authorized" in reason


@pytest.mark.asyncio
async def test_sensitive_step_ticket_authorization_success():
    pm = PermissionManager()
    cap = Capability(
        name="SystemCommandTool",
        description="Execute command",
        permission_level=PermissionLevel.SENSITIVE,
        requires_confirmation=True
    )
    params = {"command": "echo authorized", "action_type": "terminal"}
    ticket = pm.issue_step_ticket(
        plan_id="plan_test_123",
        step_id=1,
        tool_name="SystemCommandTool",
        parameters=params
    )
    ctx = {
        "device_id": "laptop-01",
        "action_payload": params,
        "step_ticket": ticket
    }
    allowed, reason = await pm.evaluate(cap, context=ctx)
    assert allowed is True
    assert reason is None


@pytest.mark.asyncio
async def test_sensitive_step_ticket_rejects_tampered_arguments():
    pm = PermissionManager()
    cap = Capability(
        name="SystemCommandTool",
        description="Execute command",
        permission_level=PermissionLevel.SENSITIVE,
        requires_confirmation=True
    )
    authorized_params = {"command": "echo safe"}
    ticket = pm.issue_step_ticket(
        plan_id="plan_test_456",
        step_id=1,
        tool_name="SystemCommandTool",
        parameters=authorized_params
    )
    # Attempt execution with tampered parameters
    tampered_ctx = {
        "device_id": "laptop-01",
        "action_payload": {"command": "rm -rf /"},
        "step_ticket": ticket
    }
    allowed, reason = await pm.evaluate(cap, context=tampered_ctx)
    assert allowed is False
    assert "SECURITY_DENIED" in reason
    assert "argument hash mismatch" in reason


@pytest.mark.asyncio
async def test_sensitive_step_ticket_single_use_enforcement():
    pm = PermissionManager()
    cap = Capability(
        name="SystemCommandTool",
        description="Execute command",
        permission_level=PermissionLevel.SENSITIVE,
        requires_confirmation=True
    )
    params = {"command": "echo single_use"}
    ticket = pm.issue_step_ticket(
        plan_id="plan_test_789",
        step_id=1,
        tool_name="SystemCommandTool",
        parameters=params
    )
    ctx = {
        "device_id": "laptop-01",
        "action_payload": params,
        "step_ticket": ticket
    }
    # 1. First execution succeeds
    allowed1, reason1 = await pm.evaluate(cap, context=ctx)
    assert allowed1 is True
    assert reason1 is None

    # 2. Second execution with same ticket must be rejected (single-use)
    allowed2, reason2 = await pm.evaluate(cap, context=ctx)
    assert allowed2 is False
    assert "already consumed" in reason2


@pytest.mark.asyncio
async def test_sensitive_rejects_blanket_confirmed_flag():
    pm = PermissionManager()
    cap = Capability(
        name="SystemCommandTool",
        description="Execute command",
        permission_level=PermissionLevel.SENSITIVE,
        requires_confirmation=True
    )
    ctx = {
        "device_id": "laptop-01",
        "action_payload": {"command": "echo bypass"},
        "confirmed": True  # Blanket confirmation attempt without ticket or token
    }
    allowed, reason = await pm.evaluate(cap, context=ctx)
    assert allowed is False
    assert "SECURITY_DENIED" in reason
    assert "Blanket confirmed=True is disallowed" in reason
