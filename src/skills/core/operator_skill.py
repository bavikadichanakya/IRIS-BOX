from __future__ import annotations
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from src.models.schemas import ProjectOperatorAction
from src.operator.resolver import WorkspaceResolver
from src.operator.summarizer import OperatorSummarizer
from src.skills.base import BaseSkill, SkillExecutionResult, SkillHealthResult, SkillManifest
from src.tools.capability import PermissionLevel

if TYPE_CHECKING:
    from src.operator.task_runner import OperatorTaskRunner

logger = logging.getLogger("iris.skills.operator")


class ProjectOperatorSkill(BaseSkill):
    """
    Core skill providing natural project operator capabilities:
    - Smart workspace resolution (active window, fuzzy search, session recency).
    - Autonomous test diagnosis and natural voice confirmations.
    - Surgical patch planning and recovery checkpoints.
    """

    def __init__(
        self,
        resolver: Optional[WorkspaceResolver] = None,
        task_runner: Optional[Any] = None,
        summarizer: Optional[OperatorSummarizer] = None,
    ):
        self.resolver = resolver or WorkspaceResolver()
        if task_runner is None:
            from src.operator.task_runner import OperatorTaskRunner
            self.task_runner = OperatorTaskRunner()
        else:
            self.task_runner = task_runner
        self.summarizer = summarizer or OperatorSummarizer()

        manifest = SkillManifest(
            name="ProjectOperatorSkill",
            version="1.0.0",
            description="Autonomous AI Project Operator: workspace resolution, test diagnosis, patching, and verification.",
            category="operator",
            permission_level=PermissionLevel.SENSITIVE,
            requires_network=False,
            timeout_seconds=60.0,
            parameters_schema=ProjectOperatorAction.model_json_schema(),
            supported_platforms=["windows", "linux", "darwin"],
        )
        super().__init__(manifest)

    async def check_health(self) -> SkillHealthResult:
        """Verify operating environment and workspace roots readiness."""
        roots_count = len(self.resolver.workspace_roots)
        return SkillHealthResult(
            skill_name=self.name,
            healthy=True,
            message=f"Project Operator ready with {roots_count} workspace roots",
            details={
                "workspace_roots": self.resolver.workspace_roots,
                "last_active_project": self.resolver.last_active_project_path,
            },
        )

    async def execute(
        self,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> SkillExecutionResult:
        start_time = time.perf_counter()
        raw_path = params.get("project_path")
        spoken_ref = params.get("spoken_reference") or params.get("project_name") or raw_path
        action = params.get("action", "diagnose")
        test_command = params.get("test_command")
        session_state = (context or {}).get("session_state") or context

        # 1. Resolve workspace path via WorkspaceResolver
        resolved_path = self.resolver.resolve_project_path(
            spoken_reference=spoken_ref,
            session_state=session_state,
        )

        if not resolved_path:
            clarification = self.summarizer.prompt_clarification()
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error="AMBIGUOUS_PROJECT",
                output={
                    "prompt": clarification,
                    "voice_response": clarification,
                    "voice_confirmation": clarification,
                    "resolved_project_path": None,
                },
                duration_ms=duration_ms,
                metadata={"needs_clarification": True},
            )

        # 2. Update active recency
        self.resolver.set_active_project(resolved_path)
        project_name = Path(resolved_path).name

        try:
            # 3. Handle requested action
            if action in ("diagnose", "diagnosis", "inspect", "test"):
                diagnostic = await self.task_runner.diagnose_failure(
                    resolved_path,
                    test_command=test_command,
                )
                voice_text = self.summarizer.summarize_diagnostic(
                    diagnostic,
                    project_name=project_name,
                )
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output={
                        "project_path": resolved_path,
                        "project_name": project_name,
                        "action": action,
                        "diagnostic": diagnostic.model_dump(),
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                        "passed": diagnostic.passed,
                    },
                    duration_ms=duration_ms,
                    metadata={"resolved_project_path": resolved_path},
                )

            elif action in ("plan", "repair_plan"):
                diagnostic = await self.task_runner.diagnose_failure(
                    resolved_path,
                    test_command=test_command,
                )
                plan = await self.task_runner.propose_surgical_patch(
                    diagnostic,
                    user_intent=params.get("intent", "Diagnose and repair project"),
                )
                voice_text = self.summarizer.summarize_plan(
                    plan,
                    project_name=project_name,
                )
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output={
                        "project_path": resolved_path,
                        "project_name": project_name,
                        "action": action,
                        "plan": plan.model_dump(),
                        "plan_id": plan.plan_id,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    duration_ms=duration_ms,
                    metadata={"resolved_project_path": resolved_path},
                )

            elif action in ("create_checkpoint", "checkpoint"):
                from src.operator.workspace import ProjectWorkspace
                cid = ProjectWorkspace.create_checkpoint(
                    resolved_path,
                    params.get("checkpoint_name", "checkpoint"),
                )
                voice_text = f"Created recovery checkpoint for {project_name}."
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output={
                        "status": "CHECKPOINT_CREATED",
                        "checkpoint_id": cid,
                        "project_path": resolved_path,
                        "project_name": project_name,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            elif action in ("rollback", "restore"):
                cid = params.get("checkpoint_id")
                if not cid:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    return SkillExecutionResult(
                        success=False,
                        skill_name=self.name,
                        error="Missing checkpoint_id for rollback",
                        duration_ms=duration_ms,
                    )
                ok = ProjectWorkspace.rollback_to_checkpoint(resolved_path, cid)
                voice_text = f"Rolled back {project_name} to checkpoint." if ok else f"Rollback failed for {project_name}."
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=ok,
                    skill_name=self.name,
                    output={
                        "status": "ROLLED_BACK" if ok else "ROLLBACK_FAILED",
                        "checkpoint_id": cid,
                        "project_path": resolved_path,
                        "voice_confirmation": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            else:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=False,
                    skill_name=self.name,
                    error=f"Unknown operator action: {action}",
                    duration_ms=duration_ms,
                )

        except Exception as e:
            logger.error(f"Error executing ProjectOperatorSkill: {e}", exc_info=True)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=f"Operator error: {str(e)}",
                duration_ms=duration_ms,
            )
