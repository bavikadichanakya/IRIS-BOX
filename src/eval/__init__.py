"""
IRIS Task Evaluation & Replay Suite.
Provides models, benchmark schemas, and execution harness for orchestrator evaluation.
"""

from src.eval.models import (
    TaskTestCase,
    TaskBenchmarkCase,
    TaskExecutionResult,
    BenchmarkReport,
)
from src.eval.replay_engine import ReplayEngine

__all__ = [
    "TaskTestCase",
    "TaskBenchmarkCase",
    "TaskExecutionResult",
    "BenchmarkReport",
    "ReplayEngine",
]
