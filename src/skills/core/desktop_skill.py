from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional

from src.models.schemas import DesktopAction
from src.operator.desktop import DesktopEnvironment
from src.operator.summarizer import OperatorSummarizer
from src.skills.base import BaseSkill, SkillExecutionResult, SkillHealthResult, SkillManifest
from src.tools.capability import PermissionLevel

logger = logging.getLogger("iris.skills.desktop")


class DesktopIntelligenceSkill(BaseSkill):
    """
    Core skill providing desktop environment and process intelligence:
    - System health & telemetry (CPU, RAM, Disk, Battery).
    - Resource bottleneck inspection (top CPU and memory processes).
    - Developer service daemon watchdog (Docker, Ollama, WSL, Postgres, Redis).
    - Desktop visible window enumeration and window focus switching.
    - Safe process termination with strict system process blacklist protection.
    """

    def __init__(
        self,
        desktop_env: Optional[DesktopEnvironment] = None,
        summarizer: Optional[OperatorSummarizer] = None,
    ):
        self.desktop_env = desktop_env or DesktopEnvironment()
        self.summarizer = summarizer or OperatorSummarizer()

        manifest = SkillManifest(
            name="desktop_intelligence",
            version="1.0.0",
            description="Inspect desktop system metrics, running processes, open windows, and local developer services",
            category="desktop",
            permission_level=PermissionLevel.PROTECTED,
            requires_network=False,
            timeout_seconds=15.0,
            parameters_schema=DesktopAction.model_json_schema(),
            supported_platforms=["windows", "linux", "darwin"],
        )
        super().__init__(manifest)

    async def check_health(self) -> SkillHealthResult:
        """Verify desktop telemetry and process inspection subsystem readiness."""
        try:
            metrics = self.desktop_env.get_system_metrics()
            return SkillHealthResult(
                skill_name=self.name,
                healthy=True,
                message="Desktop intelligence runtime ready",
                details={
                    "cpu_percent": metrics.get("cpu_percent"),
                    "memory_percent": metrics.get("memory_percent"),
                    "disk_percent": metrics.get("disk_percent"),
                },
            )
        except Exception as e:
            return SkillHealthResult(
                skill_name=self.name,
                healthy=False,
                message=f"Desktop intelligence health check failed: {e}",
            )

    async def execute(
        self,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> SkillExecutionResult:
        start_time = time.perf_counter()
        action = params.get("action", "get_system_metrics")
        ctx = context or {}

        try:
            # 1. System Health & Telemetry
            if action in ("get_system_metrics", "metrics", "telemetry", "system_metrics"):
                metrics = self.desktop_env.get_system_metrics()
                voice_text = self.summarizer.summarize_system_health(metrics)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "metrics": metrics,
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            # 2. Resource Bottleneck & Process Inspector
            elif action in ("get_top_processes", "top_processes", "processes"):
                sort_by = params.get("sort_by", "cpu")
                limit = int(params.get("limit", 5))
                procs = self.desktop_env.get_top_processes(limit=limit, sort_by=sort_by)
                voice_text = self.summarizer.summarize_top_consumers(procs, resource_type=sort_by)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "sort_by": sort_by,
                        "limit": limit,
                        "processes": procs,
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            # 3. Developer Service & Daemon Watchdog
            elif action in ("check_service", "inspect_service", "service"):
                sname = params.get("service_name") or "docker"
                service_info = self.desktop_env.inspect_service(sname)
                voice_text = self.summarizer.summarize_service_status(
                    sname,
                    service_info["running"],
                    service_info,
                )
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "service_name": sname,
                        "service": service_info,
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            # 4. Desktop Window State Inspector
            elif action in ("get_visible_windows", "windows", "list_windows"):
                windows = self.desktop_env.get_visible_windows()
                voice_text = f"Found {len(windows)} open application windows."
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "windows": windows,
                        "count": len(windows),
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            # 5. Window Focus Switcher
            elif action in ("focus_window", "focus"):
                hwnd = params.get("hwnd")
                if not hwnd:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    return SkillExecutionResult(
                        success=False,
                        skill_name=self.name,
                        error="Missing 'hwnd' parameter for focus_window.",
                        duration_ms=duration_ms,
                    )
                ok = self.desktop_env.focus_window(int(hwnd))
                voice_text = f"Switched focus to window {hwnd}." if ok else f"Unable to focus window {hwnd}."
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=ok,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "hwnd": hwnd,
                        "focused": ok,
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            # 6. Process Killer (Elevated to SENSITIVE Tier)
            elif action in ("kill_process", "kill", "terminate_process"):
                pid = params.get("pid")
                if pid is None:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    return SkillExecutionResult(
                        success=False,
                        skill_name=self.name,
                        error="Missing 'pid' parameter for kill_process.",
                        duration_ms=duration_ms,
                    )

                pid = int(pid)

                # Permission Tier Check: Terminating a process requires explicit confirmation
                is_authorized = (
                    ctx.get("confirmed") is True
                    or bool(ctx.get("confirmation_token"))
                    or bool(ctx.get("step_ticket"))
                )

                if not is_authorized:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    return SkillExecutionResult(
                        success=False,
                        skill_name=self.name,
                        error="CONFIRMATION_REQUIRED: Terminating a process requires explicit user confirmation.",
                        output={
                            "status": "CONFIRMATION_REQUIRED",
                            "action": "kill_process",
                            "pid": pid,
                            "prompt": f"Are you sure you want to terminate process {pid}?",
                            "voice_confirmation": f"Terminating process {pid} requires confirmation.",
                            "permission_level": PermissionLevel.SENSITIVE.value,
                        },
                        duration_ms=duration_ms,
                        metadata={
                            "requires_confirmation": True,
                            "permission_level": "SENSITIVE",
                        },
                    )

                # Attempt termination with system blacklist verification
                killed = self.desktop_env.kill_process(pid)
                voice_text = f"Terminated process {pid}."
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=killed,
                    skill_name=self.name,
                    output={
                        "status": "TERMINATED",
                        "pid": pid,
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            else:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=False,
                    skill_name=self.name,
                    error=f"Unknown desktop action: {action}",
                    duration_ms=duration_ms,
                )

        except PermissionError as pe:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(f"Security rejection in DesktopIntelligenceSkill: {pe}")
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=str(pe),
                output={"status": "SECURITY_DENIED"},
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"Error executing DesktopIntelligenceSkill action '{action}': {exc}", exc_info=True)
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=str(exc),
                duration_ms=duration_ms,
            )
