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
from src.eval.dataset import get_standard_benchmark_suite, BENCHMARK_CASES_6_DOMAINS
from src.eval.comparator import ModelComparator, ModelComparisonReport

__all__ = [
    "TaskTestCase",
    "TaskBenchmarkCase",
    "TaskExecutionResult",
    "BenchmarkReport",
    "ReplayEngine",
    "get_standard_benchmark_suite",
    "BENCHMARK_CASES_6_DOMAINS",
    "ModelComparator",
    "ModelComparisonReport",
]
