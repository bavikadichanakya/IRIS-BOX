"""
IRIS AI Project Operator: Autonomous workspace discovery, diagnostic, patch planning, and verifiable execution.
"""

from src.operator.workspace import ProjectWorkspace, ProjectSnapshot
from src.operator.task_runner import OperatorTaskRunner, DiagnosticReport

__all__ = [
    "ProjectWorkspace",
    "ProjectSnapshot",
    "OperatorTaskRunner",
    "DiagnosticReport",
]
