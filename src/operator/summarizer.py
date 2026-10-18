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
