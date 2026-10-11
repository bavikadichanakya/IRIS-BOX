import asyncio
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from src.tools.capability import ExecutionStatus, PermissionLevel

logger = logging.getLogger("iris.agent.plan_manager")


class StepStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    STAGED = "STAGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PlanStep(BaseModel):
    step_id: int  # 1-indexed order
    tool_name: str
    action_type: str = "execution"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str  # human-readable explanation of what this step changes
    permission_level: PermissionLevel = PermissionLevel.PUBLIC
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExecutionPlan(BaseModel):
    plan_id: str  # e.g. plan_<uuid>
    session_id: str = "default-session"
    device_id: str = "unknown"
    summary: str
    steps: List[PlanStep] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.STAGED
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 300.0)  # default 5 minutes TTL


class PlanManager:
    """
    Manages structured execution plans: creation, TTL tracking, approval, rejection,
    and truthful sequential step execution through ToolManager.
    """

    def __init__(self, default_ttl_sec: float = 300.0):
        self._plans: Dict[str, ExecutionPlan] = {}
        self.default_ttl_sec = default_ttl_sec

    def create_plan(
        self,
        session_id: str = "default-session",
        device_id: str = "unknown",
        summary: str = "",
        steps: Optional[List[Union[PlanStep, Dict[str, Any]]]] = None,
        ttl_sec: Optional[float] = None,
    ) -> ExecutionPlan:
        """Create and stage a new ExecutionPlan."""
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        now = time.time()
        ttl = ttl_sec if ttl_sec is not None else self.default_ttl_sec
        expires_at = now + ttl

        parsed_steps: List[PlanStep] = []
        for idx, s in enumerate(steps or []):
            if isinstance(s, PlanStep):
                step_obj = s
            elif isinstance(s, dict):
                step_data = dict(s)
                if "step_id" not in step_data:
                    step_data["step_id"] = idx + 1
                step_obj = PlanStep(**step_data)
            else:
                raise TypeError(f"Invalid step type: {type(s)}")
            parsed_steps.append(step_obj)

        plan = ExecutionPlan(
            plan_id=plan_id,
            session_id=session_id,
            device_id=device_id,
            summary=summary,
            steps=parsed_steps,
            status=PlanStatus.STAGED,
            created_at=now,
            expires_at=expires_at,
        )
        self._plans[plan_id] = plan
        logger.info(f"Staged execution plan '{plan_id}' with {len(parsed_steps)} steps. TTL={ttl}s")
        return plan

    def get_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        """Retrieve a plan by ID, verifying TTL expiration."""
        plan = self._plans.get(plan_id)
        if not plan:
            return None

        # Check TTL expiration
        if time.time() > plan.expires_at and plan.status == PlanStatus.STAGED:
            plan.status = PlanStatus.EXPIRED
            for step in plan.steps:
                if step.status == StepStatus.PENDING:
                    step.status = StepStatus.CANCELLED

        return plan

    def approve_plan(self, plan_id: str, token: Optional[str] = None) -> bool:
        """
        Approve a staged plan for execution.
        Returns False if plan does not exist, is expired, or is not in STAGED status.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return False

        if plan.status != PlanStatus.STAGED:
            logger.warning(f"Cannot approve plan '{plan_id}' with status {plan.status}")
            return False

        if time.time() > plan.expires_at:
            plan.status = PlanStatus.EXPIRED
            return False

        plan.status = PlanStatus.APPROVED
        logger.info(f"Execution plan '{plan_id}' approved.")
        return True

    def reject_plan(self, plan_id: str, reason: Optional[str] = None) -> bool:
        """
        Reject and discard a staged plan.
        Returns False if plan cannot be rejected.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return False

        if plan.status in (PlanStatus.REJECTED, PlanStatus.COMPLETED, PlanStatus.EXECUTING):
            return False

        plan.status = PlanStatus.REJECTED
        for step in plan.steps:
            if step.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS):
                step.status = StepStatus.CANCELLED

        logger.info(f"Execution plan '{plan_id}' rejected. Reason: {reason or 'None provided'}")
        return True

    async def execute_approved_plan(
        self,
        plan_id: str,
        orchestrator: Any
    ) -> ExecutionPlan:
        """
        Sequentially execute steps for an APPROVED plan with ToolManager.
        Halts immediately upon any step failure or cancellation.
        Updates each PlanStep.status and PlanStep.result truth-first.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan '{plan_id}' not found.")

        if plan.status != PlanStatus.APPROVED:
            raise RuntimeError(
                f"Cannot execute plan '{plan_id}' with status '{plan.status}'. Plan must be APPROVED."
            )

        tool_manager = getattr(orchestrator, "tool_manager", orchestrator)
        if not tool_manager or not hasattr(tool_manager, "execute_tool"):
            from src.tools.manager import ToolManager
            tool_manager = ToolManager()

        plan.status = PlanStatus.EXECUTING
        has_failed = False

        for idx, step in enumerate(plan.steps):
            step.status = StepStatus.IN_PROGRESS
            step_args = dict(step.parameters)
            if step.tool_name == "SystemCommandTool" and "action_type" not in step_args:
                step_args["action_type"] = step.action_type or "terminal"

            context = {
                "session_id": plan.session_id,
                "device_id": plan.device_id or "default-device",
                "device_type": "pod",
                "confirmed": True,  # Approved plan explicitly confirms steps
                "action_payload": step_args,
            }

            try:
                res = await tool_manager.execute_tool(
                    name=step.tool_name,
                    arguments=step_args,
                    context=context,
                )

                if res.status == ExecutionStatus.SUCCEEDED:
                    step.status = StepStatus.COMPLETED
                    step.result = {
                        "status": res.status.value,
                        "output": res.output,
                        "duration_ms": res.duration_ms,
                        "tool_name": step.tool_name,
                    }
                    step.error = None
                else:
                    step.status = StepStatus.FAILED
                    step.error = res.error or f"Tool '{step.tool_name}' returned status {res.status.value}"
                    step.result = {
                        "status": res.status.value,
                        "output": res.output,
                        "duration_ms": res.duration_ms,
                        "tool_name": step.tool_name,
                    }
                    plan.status = PlanStatus.FAILED
                    has_failed = True
                    # Mark all subsequent steps as CANCELLED
                    for subsequent_step in plan.steps[idx + 1:]:
                        subsequent_step.status = StepStatus.CANCELLED
                    break

            except Exception as exc:
                logger.error(f"Execution error on step {step.step_id} ({step.tool_name}): {exc}", exc_info=True)
                step.status = StepStatus.FAILED
                step.error = str(exc)
                step.result = {
                    "status": ExecutionStatus.FAILED.value,
                    "error": str(exc),
                    "tool_name": step.tool_name,
                }
                plan.status = PlanStatus.FAILED
                has_failed = True
                for subsequent_step in plan.steps[idx + 1:]:
                    subsequent_step.status = StepStatus.CANCELLED
                break

        if not has_failed:
            plan.status = PlanStatus.COMPLETED

        # Feed executed plan state back into orchestrator if available
        if hasattr(orchestrator, "session_memory") and plan.session_id:
            try:
                completed_count = sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED)
                msg = f"Plan '{plan.summary}' finished with status {plan.status.value}. Completed {completed_count}/{len(plan.steps)} steps."
                orchestrator.session_memory.add_message(plan.session_id, "assistant", msg)
            except Exception:
                pass

        if hasattr(orchestrator, "database") and orchestrator.database:
            try:
                import asyncio
                task = orchestrator.database.record_audit_event(
                    event_type="plan.executed",
                    payload={"plan_id": plan.plan_id, "status": plan.status.value, "summary": plan.summary},
                    correlation_id=plan.session_id,
                    device_id=plan.device_id,
                )
                if asyncio.iscoroutine(task):
                    asyncio.create_task(task)
            except Exception:
                pass

        return plan

    def list_active_plans(self) -> List[ExecutionPlan]:
        """List currently active, staged, or approved plans."""
        active: List[ExecutionPlan] = []
        for pid in list(self._plans.keys()):
            p = self.get_plan(pid)
            if p and p.status in (PlanStatus.STAGED, PlanStatus.APPROVED, PlanStatus.EXECUTING):
                active.append(p)
        return active
