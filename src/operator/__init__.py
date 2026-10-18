"""
IRIS AI Project Operator: Autonomous workspace discovery, diagnostic, patch planning, and verifiable execution.
"""

from src.operator.workspace import ProjectWorkspace, ProjectSnapshot
from src.operator.task_runner import OperatorTaskRunner, DiagnosticReport
from src.operator.resolver import WorkspaceResolver, parse_window_title
from src.operator.summarizer import OperatorSummarizer
from src.operator.desktop import DesktopEnvironment
from src.operator.window_manager import WindowManager
from src.operator.app_launcher import AppLauncher

__all__ = [
    "ProjectWorkspace",
    "ProjectSnapshot",
    "OperatorTaskRunner",
    "DiagnosticReport",
    "WorkspaceResolver",
    "parse_window_title",
    "OperatorSummarizer",
    "DesktopEnvironment",
    "WindowManager",
    "AppLauncher",
]


