from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.operator.task_runner import DiagnosticReport
    from src.agent.plan_manager import ExecutionPlan


class OperatorSummarizer:
    """
    Generates concise, natural spoken voice summaries for the AI Project Operator.
    Used for TTS pipeline confirmations and voice interactions.
    """

    @staticmethod
    def prompt_clarification() -> str:
        """Prompt user when workspace project cannot be resolved."""
        return "Which project should I inspect?"

    @staticmethod
    def summarize_diagnostic(diagnostic: DiagnosticReport, project_name: Optional[str] = None) -> str:
        """
        Produce a natural voice summary of test suite diagnostic results.
        Example: "Inspecting your auth-service project. One test failed in test_auth.py..."
        """
        pname = project_name or Path(diagnostic.project_path).name or "project"

        if diagnostic.passed:
            return f"Inspecting your {pname} project. All tests are passing!"

        fail_count = len(diagnostic.failing_tests)
        target_f = diagnostic.target_file or "test suite"
        root_summary = diagnostic.error_summary or "assertion error"
        # Truncate summary if too long for TTS
        if len(root_summary) > 60:
            root_summary = root_summary[:57] + "..."

        if fail_count <= 1:
            return (
                f"Inspecting your {pname} project. One test failed in {target_f}. "
                f"Error: {root_summary}."
            )
        else:
            return (
                f"Inspecting your {pname} project. {fail_count} tests failed in {target_f}. "
                f"Root cause: {root_summary}."
            )

    @staticmethod
    def summarize_plan(plan: ExecutionPlan, project_name: Optional[str] = None) -> str:
        """
        Produce a natural voice summary for a staged repair plan.
        """
        pname = project_name or (Path(plan.project_path).name if plan.project_path else "the project")
        return (
            f"I have staged a surgical repair plan for {pname}. "
            f"Would you like me to create a recovery checkpoint, apply the patch, and verify the tests?"
        )

    @staticmethod
    def summarize_system_health(metrics: Dict[str, Any]) -> str:
        """
        Produce a concise, natural voice summary of system health and telemetry.
        Example: "CPU is at 14%, RAM is at 62% with 6.1 GB available. Running on battery at 85%."
        """
        cpu = metrics.get("cpu_percent", 0)
        ram = metrics.get("memory_percent", 0)
        avail = metrics.get("available_ram_gb")
        batt_pct = metrics.get("battery_percent")
        plugged = metrics.get("power_plugged")

        msg = f"CPU is at {int(round(cpu))}%, RAM is at {int(round(ram))}%"
        if avail is not None:
            msg += f" with {avail} GB available."
        else:
            msg += "."

        if batt_pct is not None:
            if plugged:
                msg += f" Connected to power at {batt_pct}%."
            else:
                msg += f" Running on battery at {batt_pct}%."
        elif plugged:
            msg += " Running on AC power."

        return msg

    @staticmethod
    def summarize_top_consumers(processes: List[Dict[str, Any]], resource_type: str = "cpu") -> str:
        """
        Produce a concise summary of the highest resource-consuming processes.
        Example (memory): "The top memory consumer is Chrome using 1.4 GB, followed by PyCharm at 980 MB."
        Example (cpu): "The top CPU consumer is python using 24.5%, followed by node at 12.0%."
        """
        if not processes:
            return f"No active {resource_type.upper()} consumer processes found."

        res_type = resource_type.lower()

        def format_usage(p: Dict[str, Any]) -> str:
            if "mem" in res_type:
                mb = p.get("memory_mb", 0)
                if mb >= 1024:
                    return f"{round(mb / 1024, 1)} GB"
                return f"{int(round(mb))} MB"
            else:
                return f"{p.get('cpu_percent', 0)}%"

        p1 = processes[0]
        n1 = p1.get("name", "Unknown").removesuffix(".exe").capitalize()
        u1 = format_usage(p1)

        if len(processes) == 1:
            return f"The top {resource_type} consumer is {n1} using {u1}."

        p2 = processes[1]
        n2 = p2.get("name", "Unknown").removesuffix(".exe").capitalize()
        u2 = format_usage(p2)

        return f"The top {resource_type} consumer is {n1} using {u1}, followed by {n2} at {u2}."

    @staticmethod
    def summarize_service_status(service_name: str, running: bool, details: Optional[Dict[str, Any]] = None) -> str:
        """
        Produce a natural voice summary of a local developer service's operational status.
        Example: "Docker is currently running on PID 8420." or "Ollama daemon is not running."
        """
        clean_name = service_name.strip()
        display_name = clean_name.upper() if clean_name.lower() == "wsl" else clean_name.capitalize()
        details = details or {}

        if running:
            pid = details.get("pid")
            if pid:
                return f"{display_name} is currently running on PID {pid}."
            return f"{display_name} is currently running."
        else:
            daemon_suffix = " daemon" if clean_name.lower() in ("ollama", "docker") else ""
            return f"{display_name}{daemon_suffix} is not running."

