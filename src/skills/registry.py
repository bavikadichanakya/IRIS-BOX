import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from src.observability.event_bus import EventBus
from src.observability.tracing import TraceContext
from src.skills.base import BaseSkill, SkillExecutionResult, SkillHealthResult, SkillManifest
from src.skills.core.browser import BrowserAutomationSkill
from src.skills.core.home_assistant import HomeAssistantSkill
from src.skills.core.system_command import SystemCommandSkill
from src.skills.core.operator_skill import ProjectOperatorSkill
from src.skills.core.desktop_skill import DesktopIntelligenceSkill
from src.skills.core.window_skill import WindowAutomationSkill
from src.tools.capability import Capability, ExecutionStatus, PermissionLevel, ToolResult

logger = logging.getLogger("iris.skills.registry")


class SkillRegistry:
    """
    Central registry for managing, validating, auditing, and executing IRIS Skills.
    Enforces the strict offline policy (blocking skills with requires_network=True
    when IRIS_ALLOW_CLOUD is disabled) and guarantees timeout containment.
    """

    def __init__(self, event_bus: Optional[EventBus] = None, auto_register_core: bool = True):
        self._skills: Dict[str, BaseSkill] = {}
        self.event_bus = event_bus or EventBus()
        if auto_register_core:
            self._register_default_skills()

    def _register_default_skills(self):
        """Register the built-in core skills."""
        self.register_skill(SystemCommandSkill())
        self.register_skill(BrowserAutomationSkill())
        self.register_skill(HomeAssistantSkill())
        self.register_skill(ProjectOperatorSkill())
        self.register_skill(DesktopIntelligenceSkill())
        self.register_skill(WindowAutomationSkill())



    def register_skill(self, skill: BaseSkill):
        """Register a new skill instance in the registry."""
        self._skills[skill.name] = skill
        logger.info(f"Registered skill '{skill.name}' (v{skill.manifest.version}, category={skill.manifest.category})")

    def get_skill(self, name: str) -> Optional[BaseSkill]:
        """Retrieve a registered skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> List[SkillManifest]:
        """Return all registered skill manifests."""
        return [skill.manifest for skill in self._skills.values()]

    async def check_all_health(self) -> Dict[str, SkillHealthResult]:
        """Perform health checks across all registered skills concurrently."""
        results: Dict[str, SkillHealthResult] = {}
        for name, skill in self._skills.items():
            try:
                results[name] = await skill.check_health()
            except Exception as e:
                logger.error(f"Error checking health for skill '{name}': {e}", exc_info=True)
                results[name] = SkillHealthResult(
                    skill_name=name,
                    healthy=False,
                    message=f"Health check failed with error: {e}",
                )
        return results

    async def execute_skill(
        self,
        name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        trace_context: Optional[TraceContext] = None
    ) -> SkillExecutionResult:
        """
        Execute a skill with strict offline policy enforcement, timeout bounds,
        and telemetry dispatches on EventBus.
        """
        start_time = time.perf_counter()
        trace = trace_context or TraceContext()
        ctx = context or {}

        skill = self.get_skill(name)
        if not skill:
            err_msg = f"Skill '{name}' is not registered."
            await self.event_bus.publish(
                "skill.execution.failed",
                {"skill": name, "error": err_msg, "duration_ms": 0.0},
                trace=trace
            )
            return SkillExecutionResult(
                success=False,
                skill_name=name,
                error=err_msg,
                duration_ms=0.0
            )

        # 1. Strict Offline Policy Check
        allow_cloud = os.getenv("IRIS_ALLOW_CLOUD", "false").lower() in ("true", "1")
        if skill.manifest.requires_network and not allow_cloud:
            err_msg = (
                f"OFFLINE_POLICY_VIOLATION: Skill '{name}' requires network access, "
                f"but external connectivity is strictly blocked (IRIS_ALLOW_CLOUD=false)."
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            await self.event_bus.publish(
                "skill.execution.failed",
                {"skill": name, "error": err_msg, "duration_ms": duration_ms},
                trace=trace
            )
            return SkillExecutionResult(
                success=False,
                skill_name=name,
                error=err_msg,
                duration_ms=duration_ms
            )

        # 2. Telemetry: Started
        await self.event_bus.publish(
            "skill.execution.started",
            {"skill": name, "params": params, "category": skill.manifest.category},
            trace=trace
        )

        # 3. Execution with Timeout Boundary
        timeout = skill.manifest.timeout_seconds
        try:
            result: SkillExecutionResult = await asyncio.wait_for(
                skill.execute(params, context=ctx),
                timeout=timeout
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            result.duration_ms = duration_ms

            if result.success:
                await self.event_bus.publish(
                    "skill.execution.completed",
                    {"skill": name, "duration_ms": duration_ms, "output": result.output},
                    trace=trace
                )
            else:
                await self.event_bus.publish(
                    "skill.execution.failed",
                    {"skill": name, "duration_ms": duration_ms, "error": result.error},
                    trace=trace
                )
            return result

        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = f"Execution timed out after {timeout}s"
            await self.event_bus.publish(
                "skill.execution.failed",
                {"skill": name, "duration_ms": duration_ms, "error": err_msg, "timeout": True},
                trace=trace
            )
            return SkillExecutionResult(
                success=False,
                skill_name=name,
                error=err_msg,
                duration_ms=duration_ms
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = str(exc)
            await self.event_bus.publish(
                "skill.execution.failed",
                {"skill": name, "duration_ms": duration_ms, "error": err_msg},
                trace=trace
            )
            return SkillExecutionResult(
                success=False,
                skill_name=name,
                error=err_msg,
                duration_ms=duration_ms
            )

    def bridge_to_tool_manager(self, tool_manager: Any):
        """
        Bridge registered skills to ToolManager so the LLM prompt and ReAct loops
        automatically expose registered skills as valid tools.
        """
        for skill in self._skills.values():
            m = skill.manifest
            cap = Capability(
                name=m.name,
                description=m.description,
                schema=m.parameters_schema,
                permission_level=m.permission_level,
                category=m.category,
                supported_devices=m.supported_platforms,
                requires_confirmation=(m.permission_level == PermissionLevel.SENSITIVE),
                execution_timeout_sec=m.timeout_seconds
            )
            tool_manager.register_capability(cap)

        # Attach registry reference so ToolManager can dispatch to execute_skill
        tool_manager.skill_registry = self
