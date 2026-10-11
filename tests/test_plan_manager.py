import asyncio
import time
from unittest.mock import Mock, patch
import pytest
from starlette.testclient import TestClient

from src.server.app import app
from src.security.auth import auth_manager
from src.agent.plan_manager import (
    PlanManager,
    PlanStep,
    ExecutionPlan,
    PlanStatus,
    StepStatus,
)
from src.tools.capability import PermissionLevel, ExecutionStatus, ToolResult
from src.tools.manager import ToolManager
from src.agent.orchestrator import IRISOrchestrator


@pytest.fixture
def plan_manager():
    return PlanManager(default_ttl_sec=300.0)


@pytest.fixture
def mock_tool_manager():
    tm = Mock(spec=ToolManager)
    # Default async execute_tool returning SUCCEEDED
    async def _mock_exec(name, arguments, context=None, request_id="", trace_id=""):
        if name == "FailingTool":
            return ToolResult(
                status=ExecutionStatus.FAILED,
                tool_name=name,
                error="Simulated tool execution error",
                duration_ms=12.0
            )
        return ToolResult(
            status=ExecutionStatus.SUCCEEDED,
            tool_name=name,
            output={"result": f"Executed {name} successfully"},
            duration_ms=10.0
        )
    tm.execute_tool = _mock_exec
    return tm


@pytest.mark.asyncio
async def test_plan_staging_and_ttl_expiration():
    """
    Verify plan creation stages the plan, and that exceeding TTL marks it as EXPIRED
    and prevents approval.
    """
    pm = PlanManager(default_ttl_sec=0.2)
    step1 = PlanStep(
        step_id=1,
        tool_name="SystemCommandTool",
        description="Echo test",
        parameters={"command": "echo test"},
        permission_level=PermissionLevel.SENSITIVE
    )
    plan = pm.create_plan(
        session_id="session-ttl",
        device_id="laptop-1",
        summary="Test TTL Plan",
        steps=[step1],
        ttl_sec=0.1
    )

    assert plan.status == PlanStatus.STAGED
    assert plan.plan_id.startswith("plan_")
    assert len(plan.steps) == 1

    # Before TTL expiry
    fetched = pm.get_plan(plan.plan_id)
    assert fetched is not None
    assert fetched.status == PlanStatus.STAGED

    # Sleep past TTL
    await asyncio.sleep(0.15)

    # After TTL expiry
    expired_plan = pm.get_plan(plan.plan_id)
    assert expired_plan is not None
    assert expired_plan.status == PlanStatus.EXPIRED
    assert expired_plan.steps[0].status == StepStatus.CANCELLED

    # Approval should be rejected for expired plans
    approved = pm.approve_plan(plan.plan_id)
    assert approved is False


def test_plan_inspection_parameters_and_descriptions(plan_manager):
    """
    Verify plan inspection returns accurate tool parameters, human-readable step descriptions,
    and assigned permission levels.
    """
    steps = [
        PlanStep(
            step_id=1,
            tool_name="SystemCommandTool",
            action_type="terminal",
            parameters={"command": "echo step1", "action_type": "terminal"},
            description="Print step 1 to console",
            permission_level=PermissionLevel.SENSITIVE
        ),
        PlanStep(
            step_id=2,
            tool_name="HomeAssistantTool",
            action_type="smart_home",
            parameters={"domain": "light", "action": "off", "entity_id": "light.bedroom"},
            description="Turn off bedroom light",
            permission_level=PermissionLevel.PROTECTED
        ),
    ]

    plan = plan_manager.create_plan(
        session_id="sess-inspect",
        device_id="pod-living-room",
        summary="Inspection Test Plan",
        steps=steps
    )

    inspected = plan_manager.get_plan(plan.plan_id)
    assert inspected is not None
    assert inspected.summary == "Inspection Test Plan"
    assert len(inspected.steps) == 2

    # Step 1 assertions
    s1 = inspected.steps[0]
    assert s1.step_id == 1
    assert s1.tool_name == "SystemCommandTool"
    assert s1.parameters == {"command": "echo step1", "action_type": "terminal"}
    assert s1.description == "Print step 1 to console"
    assert s1.permission_level == PermissionLevel.SENSITIVE
    assert s1.status == StepStatus.PENDING
    assert s1.result is None
    assert s1.error is None

    # Step 2 assertions
    s2 = inspected.steps[1]
    assert s2.step_id == 2
    assert s2.tool_name == "HomeAssistantTool"
    assert s2.parameters == {"domain": "light", "action": "off", "entity_id": "light.bedroom"}
    assert s2.description == "Turn off bedroom light"
    assert s2.permission_level == PermissionLevel.PROTECTED
    assert s2.status == StepStatus.PENDING


@pytest.mark.asyncio
async def test_successful_approval_and_ordered_sequential_execution(plan_manager, mock_tool_manager):
    """
    Verify successful approval followed by ordered sequential step execution,
    updating step statuses and outputs truth-first.
    """
    steps = [
        PlanStep(
            step_id=1,
            tool_name="SystemCommandTool",
            description="Run first action",
            parameters={"command": "echo 1"}
        ),
        PlanStep(
            step_id=2,
            tool_name="SystemCommandTool",
            description="Run second action",
            parameters={"command": "echo 2"}
        ),
    ]

    plan = plan_manager.create_plan(summary="Ordered Execution", steps=steps)
    assert plan.status == PlanStatus.STAGED

    # Approve
    approved = plan_manager.approve_plan(plan.plan_id)
    assert approved is True
    assert plan.status == PlanStatus.APPROVED

    # Execute
    executed = await plan_manager.execute_approved_plan(plan.plan_id, orchestrator=mock_tool_manager)
    assert executed.status == PlanStatus.COMPLETED

    assert executed.steps[0].status == StepStatus.COMPLETED
    assert executed.steps[0].result["status"] == "SUCCEEDED"
    assert executed.steps[0].error is None

    assert executed.steps[1].status == StepStatus.COMPLETED
    assert executed.steps[1].result["status"] == "SUCCEEDED"
    assert executed.steps[1].error is None


@pytest.mark.asyncio
async def test_immediate_execution_halt_on_intermediate_failure(plan_manager, mock_tool_manager):
    """
    Verify that an intermediate step failure immediately halts execution,
    leaving subsequent steps in CANCELLED status.
    """
    steps = [
        PlanStep(
            step_id=1,
            tool_name="SystemCommandTool",
            description="Step 1 succeeds",
            parameters={"command": "echo 1"}
        ),
        PlanStep(
            step_id=2,
            tool_name="FailingTool",
            description="Step 2 fails",
            parameters={"action": "fail"}
        ),
        PlanStep(
            step_id=3,
            tool_name="SystemCommandTool",
            description="Step 3 should never run",
            parameters={"command": "echo 3"}
        ),
    ]

    plan = plan_manager.create_plan(summary="Failure Halt Plan", steps=steps)
    plan_manager.approve_plan(plan.plan_id)

    executed = await plan_manager.execute_approved_plan(plan.plan_id, orchestrator=mock_tool_manager)

    assert executed.status == PlanStatus.FAILED
    assert executed.steps[0].status == StepStatus.COMPLETED
    assert executed.steps[1].status == StepStatus.FAILED
    assert "Simulated tool execution error" in (executed.steps[1].error or "")
    assert executed.steps[2].status == StepStatus.CANCELLED
    assert executed.steps[2].result is None


@pytest.mark.asyncio
async def test_rejection_workflow_prevents_execution(plan_manager, mock_tool_manager):
    """
    Verify rejection transitions plan to REJECTED, cancels pending steps,
    and blocks subsequent approval or execution.
    """
    steps = [
        PlanStep(
            step_id=1,
            tool_name="SystemCommandTool",
            description="Dangerous task",
            parameters={"command": "echo dangerous"}
        )
    ]
    plan = plan_manager.create_plan(summary="Reject Plan", steps=steps)

    # Reject plan
    rejected = plan_manager.reject_plan(plan.plan_id, reason="User cancelled")
    assert rejected is True
    assert plan.status == PlanStatus.REJECTED
    assert plan.steps[0].status == StepStatus.CANCELLED

    # Cannot approve a rejected plan
    assert plan_manager.approve_plan(plan.plan_id) is False

    # Execution should fail immediately
    with pytest.raises(RuntimeError) as exc_info:
        await plan_manager.execute_approved_plan(plan.plan_id, orchestrator=mock_tool_manager)
    assert "Plan must be APPROVED" in str(exc_info.value)


@pytest.mark.asyncio
async def test_orchestrator_multi_action_plan_preview():
    """
    Verify orchestrator detects explicit multi-action plan requests and returns
    structured PLAN_PREVIEW_REQUIRED result without executing tools unguided.
    """
    orchestrator = IRISOrchestrator(
        api_base="http://localhost:11434/v1",
        api_key="ollama",
        model="qwen2.5:7b-instruct"
    )

    # Explicit plan request
    prompt = "Create an execution plan to echo hello and dir"
    result = orchestrator.process_request(prompt)

    assert result.success is True
    assert result.status == "PLAN_PREVIEW_REQUIRED"
    assert result.output_payload["status"] == "PLAN_PREVIEW_REQUIRED"
    plan_id = result.output_payload["plan_id"]
    assert plan_id is not None
    steps = result.output_payload["steps"]
    assert len(steps) >= 2

    # Verify plan is staged in PlanManager
    staged = orchestrator.plan_manager.get_plan(plan_id)
    assert staged is not None
    assert staged.status == PlanStatus.STAGED

    # Approve and execute via Orchestrator
    orchestrator.plan_manager.approve_plan(plan_id)
    exec_result = await orchestrator.execute_plan(plan_id)
    assert exec_result.status == "COMPLETED"
    assert exec_result.output_payload["status"] == "COMPLETED"
    assert "response" in exec_result.output_payload


def test_plans_rest_api_security_and_endpoints():
    """
    Verify REST API authentication boundaries (HTTP 401 on missing auth),
    plan inspection, approval execution, and rejection endpoints.
    """
    client = TestClient(app)
    pm = PlanManager()
    app.state.plan_manager = pm

    # 1. Unauthenticated Security Boundary: Must return HTTP 401
    res_unauth_active = client.get("/api/plans/active")
    assert res_unauth_active.status_code == 401

    res_unauth_inspect = client.get("/api/plans/plan_dummy123")
    assert res_unauth_inspect.status_code == 401

    res_unauth_approve = client.post("/api/plans/plan_dummy123/approve")
    assert res_unauth_approve.status_code == 401

    res_unauth_reject = client.post("/api/plans/plan_dummy123/reject")
    assert res_unauth_reject.status_code == 401

    # 2. Authenticated Endpoints
    headers = {"X-API-Key": auth_manager.master_key}

    # Staged plan for rejection test
    plan_to_reject = pm.create_plan(
        summary="API Reject Test",
        steps=[PlanStep(step_id=1, tool_name="SystemCommandTool", description="Test action")]
    )

    # Active listing
    active_res = client.get("/api/plans/active", headers=headers)
    assert active_res.status_code == 200
    active_data = active_res.json()
    assert any(p["plan_id"] == plan_to_reject.plan_id for p in active_data["plans"])

    # Inspection
    inspect_res = client.get(f"/api/plans/{plan_to_reject.plan_id}", headers=headers)
    assert inspect_res.status_code == 200
    assert inspect_res.json()["plan_id"] == plan_to_reject.plan_id
    assert inspect_res.json()["status"] == "STAGED"

    # Rejection via API
    reject_res = client.post(
        f"/api/plans/{plan_to_reject.plan_id}/reject",
        json={"reason": "User declined in UI"},
        headers=headers
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "REJECTED"

    # Cannot approve rejected plan -> HTTP 400
    re_approve_res = client.post(f"/api/plans/{plan_to_reject.plan_id}/approve", headers=headers)
    assert re_approve_res.status_code == 400

    # 3. Authenticated Approval & Execution Flow
    plan_to_approve = pm.create_plan(
        summary="API Approve Test",
        steps=[PlanStep(step_id=1, tool_name="SystemCommandTool", parameters={"command": "echo api_ok", "action_type": "terminal"}, description="Run echo")]
    )
    approve_res = client.post(f"/api/plans/{plan_to_approve.plan_id}/approve", headers=headers)
    assert approve_res.status_code == 200
    approve_data = approve_res.json()
    assert approve_data["plan_id"] == plan_to_approve.plan_id
    assert approve_data["status"] == "COMPLETED"
    assert approve_data["steps"][0]["status"] == "COMPLETED"
