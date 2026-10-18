from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional

from src.models.schemas import WindowAutomationAction
from src.operator.app_launcher import AppLauncher
from src.operator.window_manager import WindowManager
from src.operator.summarizer import OperatorSummarizer
from src.skills.base import BaseSkill, SkillExecutionResult, SkillHealthResult, SkillManifest
from src.tools.capability import PermissionLevel

logger = logging.getLogger("iris.skills.window_automation")


class WindowAutomationSkill(BaseSkill):
    """
    Core skill for application launching, window focus switching, and window state control.
    """

    def __init__(
        self,
        window_mgr: Optional[WindowManager] = None,
        app_launcher: Optional[AppLauncher] = None,
        summarizer: Optional[OperatorSummarizer] = None,
    ):
        self.window_mgr = window_mgr or WindowManager()
        self.app_launcher = app_launcher or AppLauncher()
        self.summarizer = summarizer or OperatorSummarizer()

        manifest = SkillManifest(
            name="window_automation",
            version="1.0.0",
            description="Control application launching, window focus switching, and window states",
            category="desktop",
            permission_level=PermissionLevel.PROTECTED,
            requires_network=False,
            timeout_seconds=15.0,
            parameters_schema=WindowAutomationAction.model_json_schema(),
            supported_platforms=["windows", "linux", "darwin"],
        )
        super().__init__(manifest)

    async def check_health(self) -> SkillHealthResult:
        """Verify window manager and app launcher readiness."""
        try:
            apps = self.app_launcher.list_known_apps()
            return SkillHealthResult(
                skill_name=self.name,
                healthy=True,
                message="Window automation runtime ready",
                details={
                    "known_apps_count": len(apps),
                },
            )
        except Exception as e:
            return SkillHealthResult(
                skill_name=self.name,
                healthy=False,
                message=f"Window automation health check failed: {e}",
            )

    async def execute(
        self,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> SkillExecutionResult:
        start_time = time.perf_counter()
        action = params.get("action", "focus_window")
        ctx = context or {}

        try:
            # 1. Launch Application
            if action in ("launch_app", "launch", "open_app", "start_app"):
                app_name = params.get("app_name") or params.get("query")
                if not app_name:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    return SkillExecutionResult(
                        success=False,
                        skill_name=self.name,
                        error="Missing 'app_name' parameter for launch_app.",
                        duration_ms=duration_ms,
                    )

                res = self.app_launcher.launch_app(str(app_name))
                voice_text = self.summarizer.summarize_app_launch(str(app_name), True, res)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "app_name": app_name,
                        "result": res,
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            # 2. Focus Window
            elif action in ("focus_window", "focus", "switch_window", "switch_to"):
                target = params.get("query") or params.get("hwnd") or params.get("app_name")
                if target is None:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    return SkillExecutionResult(
                        success=False,
                        skill_name=self.name,
                        error="Missing 'query' or 'hwnd' parameter for focus_window.",
                        duration_ms=duration_ms,
                    )

                matched_win = self.window_mgr.find_window(target)
                win_title = matched_win.get("title") if matched_win else str(target)
                ok = self.window_mgr.focus_window(target)
                voice_text = self.summarizer.summarize_window_focus(str(target), ok, win_title)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=ok,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "target": target,
                        "window": matched_win,
                        "focused": ok,
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    error=None if ok else f"Could not find or focus window matching '{target}'.",
                    duration_ms=duration_ms,
                )

            # 3. Set Window State (Maximize, Minimize, Restore)
            elif action in ("set_window_state", "window_state", "state"):
                target = params.get("query") or params.get("hwnd") or params.get("app_name")
                state = params.get("state", "maximize")
                if target is None:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    return SkillExecutionResult(
                        success=False,
                        skill_name=self.name,
                        error="Missing 'query' or 'hwnd' parameter for set_window_state.",
                        duration_ms=duration_ms,
                    )

                matched_win = self.window_mgr.find_window(target)
                win_title = matched_win.get("title") if matched_win else str(target)
                ok = self.window_mgr.set_window_state(target, state)
                voice_text = self.summarizer.summarize_window_state(win_title, state, ok)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=ok,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "target": target,
                        "state": state,
                        "window": matched_win,
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    error=None if ok else f"Failed to {state} window '{target}'.",
                    duration_ms=duration_ms,
                )

            # 4. Close Window (Elevated to SENSITIVE Tier)
            elif action in ("close_window", "close"):
                target = params.get("query") or params.get("hwnd") or params.get("app_name")
                if target is None:
                    duration_ms = (time.perf_counter() - start_time) * 1000.0
                    return SkillExecutionResult(
                        success=False,
                        skill_name=self.name,
                        error="Missing 'query' or 'hwnd' parameter for close_window.",
                        duration_ms=duration_ms,
                    )

                matched_win = self.window_mgr.find_window(target)
                win_title = matched_win.get("title") if matched_win else str(target)

                # Permission Tier Check: Closing an application window requires confirmation
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
                        error=f"CONFIRMATION_REQUIRED: Closing window '{win_title}' requires explicit user confirmation.",
                        output={
                            "status": "CONFIRMATION_REQUIRED",
                            "action": "close_window",
                            "target": target,
                            "window_title": win_title,
                            "prompt": f"Are you sure you want to close window '{win_title}'?",
                            "voice_confirmation": f"Closing window '{win_title}' requires confirmation.",
                            "permission_level": PermissionLevel.SENSITIVE.value,
                        },
                        duration_ms=duration_ms,
                        metadata={
                            "requires_confirmation": True,
                            "permission_level": "SENSITIVE",
                        },
                    )

                ok = self.window_mgr.close_window(target)
                voice_text = self.summarizer.summarize_window_close(win_title, ok)
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=ok,
                    skill_name=self.name,
                    output={
                        "action": action,
                        "target": target,
                        "window_title": win_title,
                        "status": "CLOSED" if ok else "CLOSE_FAILED",
                        "voice_summary": voice_text,
                        "voice_confirmation": voice_text,
                        "voice_response": voice_text,
                    },
                    duration_ms=duration_ms,
                )

            else:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=False,
                    skill_name=self.name,
                    error=f"Unknown window automation action: {action}",
                    duration_ms=duration_ms,
                )

        except PermissionError as pe:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(f"Security rejection in WindowAutomationSkill: {pe}")
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=str(pe),
                output={"status": "SECURITY_DENIED"},
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"Error executing WindowAutomationSkill action '{action}': {exc}", exc_info=True)
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=str(exc),
                duration_ms=duration_ms,
            )
