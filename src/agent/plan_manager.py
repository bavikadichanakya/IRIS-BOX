import asyncio
import logging
import time
import uuid
import json
import hashlib
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
    content_hash: str = Field(default="", description="Cryptographic SHA256 digest of canonical plan structure")
    approval_token: Optional[str] = Field(default=None, description="Single-use approval token bound to content_hash")
    diff_preview: Optional[str] = Field(default=None, description="Unified diff showing exact changes before approval")
    checkpoint_id: Optional[str] = Field(default=None, description="Workspace rollback checkpoint ID")
    project_path: Optional[str] = Field(default=None, description="Target workspace project path")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary execution plan metadata")
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

    def calculate_content_hash(self, plan_id: str, steps: List[PlanStep]) -> str:
        """
        Computes a deterministic SHA256 digest of the canonical plan payload
        (plan_id + ordered step definitions + parameters).
        """
        canonical_steps = [
            {
                "step_id": s.step_id,
                "tool_name": s.tool_name,
                "action_type": s.action_type,
                "parameters": s.parameters,
                "permission_level": s.permission_level.value if hasattr(s.permission_level, "value") else str(s.permission_level),
            }
            for s in sorted(steps, key=lambda x: x.step_id)
        ]
        canonical_payload = {
            "plan_id": plan_id,
            "steps": canonical_steps,
        }
        canonical_bytes = json.dumps(canonical_payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()

    def create_plan(
        self,
        session_id: str = "default-session",
        device_id: str = "unknown",
        summary: str = "",
        steps: Optional[List[Union[PlanStep, Dict[str, Any]]]] = None,
        ttl_sec: Optional[float] = None,
        diff_preview: Optional[str] = None,
        checkpoint_id: Optional[str] = None,
        project_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """Create, cryptographically digest, and stage a new ExecutionPlan."""
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
            if step_obj.permission_level == PermissionLevel.PUBLIC:
                name = step_obj.tool_name
                action = (step_obj.action_type or (step_obj.parameters.get("action") if step_obj.parameters else "")).lower()
                if action in ("checkpoint", "create_checkpoint", "validate_exit_code", "verify", "verification", "read_only", "snapshot"):
                    step_obj.permission_level = PermissionLevel.PUBLIC
                elif action in ("test", "run_test"):
                    step_obj.permission_level = PermissionLevel.PROTECTED
                elif "System" in name or "Terminal" in name or "Shell" in name or "Bash" in name or "PowerShell" in name or "Patch" in name or action in ("patch", "apply_patch", "modify"):
                    step_obj.permission_level = PermissionLevel.SENSITIVE
                elif "Home" in name or "Assistant" in name or "Device" in name:
                    step_obj.permission_level = PermissionLevel.PROTECTED
            parsed_steps.append(step_obj)

        content_hash = self.calculate_content_hash(plan_id, parsed_steps)

        # Cryptographically issue single-use plan approval token bound to plan_id and content_hash
        from src.security.auth import auth_manager
        approval_token = auth_manager.create_plan_approval_token(plan_id, content_hash, ttl_sec=ttl)

        plan = ExecutionPlan(
            plan_id=plan_id,
            session_id=session_id,
            device_id=device_id,
            summary=summary,
            steps=parsed_steps,
            status=PlanStatus.STAGED,
            content_hash=content_hash,
            approval_token=approval_token,
            diff_preview=diff_preview,
            checkpoint_id=checkpoint_id,
            project_path=project_path,
            metadata=metadata or {},
            created_at=now,
            expires_at=expires_at,
        )
        self._plans[plan_id] = plan
        logger.info(f"Staged execution plan '{plan_id}' with {len(parsed_steps)} steps. Hash={content_hash[:8]}... TTL={ttl}s")
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
        Cryptographically approve a staged plan for execution.
        Requires a non-empty token that binds to the plan digest.
        Returns False if plan does not exist, is expired, not in STAGED status,
        or if token is missing, expired, or mismatched.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            logger.warning(f"Cannot approve non-existent plan '{plan_id}'")
            return False

        if plan.status != PlanStatus.STAGED:
            logger.warning(f"Cannot approve plan '{plan_id}' with status {plan.status}")
            return False

        if time.time() > plan.expires_at:
            plan.status = PlanStatus.EXPIRED
            logger.warning(f"Cannot approve expired plan '{plan_id}'")
            return False

        if not token or not token.strip():
            logger.warning(f"Cannot approve plan '{plan_id}': token is missing or empty.")
            return False

        from src.security.auth import auth_manager
        if not auth_manager.validate_plan_approval_token(plan_id, plan.content_hash, token.strip()):
            logger.warning(f"Cryptographic token validation failed for plan '{plan_id}' approval.")
            return False

        plan.status = PlanStatus.APPROVED
        logger.info(f"Execution plan '{plan_id}' approved with verified cryptographic token.")
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

            # Per-step explicit authorization ticket for sensitive actions
            step_ticket = None
            is_sensitive = (step.permission_level == PermissionLevel.SENSITIVE)
            if not is_sensitive and hasattr(tool_manager, "get_capability"):
                cap = tool_manager.get_capability(step.tool_name)
                if cap and cap.permission_level == PermissionLevel.SENSITIVE:
                    is_sensitive = True
            elif not is_sensitive:
                name = step.tool_name
                if "System" in name or "Terminal" in name or "Shell" in name or "Bash" in name:
                    is_sensitive = True

            if is_sensitive:
                perm_mgr = getattr(tool_manager, "permission_manager", None)
                if not perm_mgr:
                    from src.tools.permissions import permission_manager as perm_mgr
                step_ticket = perm_mgr.issue_step_ticket(
                    plan_id=plan.plan_id,
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    parameters=step_args,
                )

            context = {
                "session_id": plan.session_id,
                "device_id": plan.device_id or "default-device",
                "device_type": "pod",
                "action_payload": step_args,
                "step_ticket": step_ticket,
            }

            try:
                res = await tool_manager.execute_tool(
                    name=step.tool_name,
                    arguments=step_args,
                    context=context,
                )

                is_process_failure = False
                exit_code = None
                output_payload = res.output
                if hasattr(output_payload, "output_payload"):
                    if not getattr(output_payload, "success", True):
                        is_process_failure = True
                    output_payload = output_payload.output_payload

                if isinstance(output_payload, dict):
                    exit_code = output_payload.get("returncode", output_payload.get("exit_code"))
                    if exit_code is not None and exit_code != 0:
                        is_process_failure = True
                    elif output_payload.get("status") in ("TEST_FAILED", "FAILED") or output_payload.get("success") is False:
                        is_process_failure = True

                if res.status == ExecutionStatus.SUCCEEDED and not is_process_failure:
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
                    step.error = res.error or (f"Step process failed with exit code {exit_code}" if exit_code is not None else f"Tool '{step.tool_name}' returned status {res.status.value}")
                    step.result = {
                        "status": ExecutionStatus.FAILED.value,
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

        if has_failed:
            plan.status = PlanStatus.FAILED
            # Trigger automatic rollback if checkpoint information exists on plan or steps
            chk_id = plan.checkpoint_id or (plan.metadata.get("checkpoint_id") if plan.metadata else None)
            proj_p = plan.project_path or (plan.metadata.get("project_path") if plan.metadata else None)
            if not chk_id:
                for s in plan.steps:
                    out = s.result.get("output") if s.result else None
                    if hasattr(out, "output_payload"):
                        out = out.output_payload
                    if isinstance(out, dict) and "checkpoint_id" in out:
                        chk_id = out["checkpoint_id"]
                        proj_p = out.get("project_path", proj_p)
                        break
                    if s.parameters and s.parameters.get("checkpoint_id"):
                        chk_id = s.parameters["checkpoint_id"]
                        proj_p = s.parameters.get("project_path", proj_p)
                        break
            if chk_id and proj_p:
                try:
                    from src.operator.workspace import ProjectWorkspace
                    reverted = ProjectWorkspace.revert_checkpoint(proj_p, chk_id)
                    logger.warning(f"Plan execution failed; triggered automatic rollback to checkpoint '{chk_id}'. Success: {reverted}")
                except Exception as rollback_err:
                    logger.error(f"Error during automatic checkpoint rollback: {rollback_err}", exc_info=True)
        else:
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
