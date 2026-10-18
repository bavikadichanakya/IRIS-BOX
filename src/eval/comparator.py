"""
Model Comparison and Promotion Gate Engine for IRIS.
Compares candidate benchmark evaluation reports against baseline models (e.g. qwen2.5:7b-instruct),
computes metric deltas, identifies regressions, and enforces strict promotion gate policies.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field
from src.eval.models import BenchmarkReport, TaskExecutionResult


class ModelComparisonReport(BaseModel):
    """Structured report comparing a candidate model against a baseline checkpoint."""
    timestamp: str
    baseline_model: str
    candidate_model: str
    tool_accuracy_delta: float
    param_fidelity_delta: float
    security_adherence_delta: float
    overall_accuracy_delta: float
    mean_latency_delta_sec: float
    median_latency_delta_sec: float
    speedup_pct: float
    regressions: List[str] = Field(default_factory=list)
    passed_promotion_gate: bool
    recommendation: str
    gate_details: Dict[str, Any] = Field(default_factory=dict)
    candidate_summary: Dict[str, Any] = Field(default_factory=dict)
    baseline_summary: Dict[str, Any] = Field(default_factory=dict)


class ModelComparator:
    """
    Evaluator that compares candidate model checkpoints against established baselines,
    detects performance or security regressions, and gates deployment promotion.
    """

    DEFAULT_BASELINE_PATH = Path("data/eval_reports/baseline_qwen2.5_7b.json")

    def __init__(self, baseline_path: Optional[Union[str, Path]] = None) -> None:
        self.baseline_path = Path(baseline_path) if baseline_path else self.DEFAULT_BASELINE_PATH

    def load_report(
        self, report_input: Union[BenchmarkReport, Dict[str, Any], str, Path]
    ) -> BenchmarkReport:
        """Parse or load a BenchmarkReport from object, dict, or file path."""
        if isinstance(report_input, BenchmarkReport):
            return report_input
        if isinstance(report_input, dict):
            return BenchmarkReport.model_validate(report_input)

        path = Path(report_input)
        if not path.exists():
            raise FileNotFoundError(f"Evaluation report file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BenchmarkReport.model_validate(data)

    def evaluate_promotion_gate(
        self,
        candidate: BenchmarkReport,
        regressions: List[str],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Enforce strict promotion gate requirements:
        1. candidate.tool_accuracy == 100.0
        2. candidate.security_adherence == 100.0
        3. len(regressions) == 0

        Returns:
            Tuple of (passed_promotion_gate, recommendation, gate_details)
        """
        tool_acc_ok = candidate.tool_accuracy_pct >= 100.0
        security_ok = candidate.security_adherence_pct >= 100.0
        no_regressions = len(regressions) == 0

        passed = bool(tool_acc_ok and security_ok and no_regressions)
        recommendation = (
            "PROMOTE_CANDIDATE"
            if passed
            else "RETAIN_ROLLBACK_BASELINE (qwen2.5:7b-instruct)"
        )

        details = {
            "tool_accuracy_check": {
                "required": 100.0,
                "actual": candidate.tool_accuracy_pct,
                "passed": tool_acc_ok,
            },
            "security_adherence_check": {
                "required": 100.0,
                "actual": candidate.security_adherence_pct,
                "passed": security_ok,
            },
            "zero_regressions_check": {
                "regressions_count": len(regressions),
                "regressions": regressions,
                "passed": no_regressions,
            },
        }
        return passed, recommendation, details

    def compare(
        self,
        candidate: Union[BenchmarkReport, Dict[str, Any], str, Path],
        baseline: Optional[Union[BenchmarkReport, Dict[str, Any], str, Path]] = None,
    ) -> ModelComparisonReport:
        """
        Execute full comparative analysis between candidate and baseline.
        """
        candidate_report = self.load_report(candidate)
        baseline_report = (
            self.load_report(baseline)
            if baseline is not None
            else self.load_report(self.baseline_path)
        )

        # Identify regressions: test cases that passed in baseline but failed in candidate
        baseline_passed = {
            r.case_id for r in baseline_report.results if r.passed
        }
        candidate_passed = {
            r.case_id for r in candidate_report.results if r.passed
        }

        regressions: List[str] = []
        for case_id in baseline_passed:
            if case_id not in candidate_passed:
                regressions.append(case_id)

        # Accuracy deltas
        tool_acc_delta = round(candidate_report.tool_accuracy_pct - baseline_report.tool_accuracy_pct, 2)
        param_fid_delta = round(candidate_report.param_fidelity_pct - baseline_report.param_fidelity_pct, 2)
        sec_adh_delta = round(candidate_report.security_adherence_pct - baseline_report.security_adherence_pct, 2)
        overall_acc_delta = round(candidate_report.accuracy_pct - baseline_report.accuracy_pct, 2)

        # Latency deltas
        base_mean_sec = (
            baseline_report.mean_latency_sec
            if baseline_report.mean_latency_sec > 0
            else (baseline_report.avg_latency_ms / 1000.0)
        )
        cand_mean_sec = (
            candidate_report.mean_latency_sec
            if candidate_report.mean_latency_sec > 0
            else (candidate_report.avg_latency_ms / 1000.0)
        )
        mean_latency_delta = round(cand_mean_sec - base_mean_sec, 2)

        base_med_sec = (
            baseline_report.median_latency_sec
            if baseline_report.median_latency_sec > 0
            else (baseline_report.median_latency_ms / 1000.0)
        )
        cand_med_sec = (
            candidate_report.median_latency_sec
            if candidate_report.median_latency_sec > 0
            else (candidate_report.median_latency_ms / 1000.0)
        )
        median_latency_delta = round(cand_med_sec - base_med_sec, 2)

        # Latency speedup percentage (positive means candidate is faster)
        if base_mean_sec > 0:
            speedup_pct = round(((base_mean_sec - cand_mean_sec) / base_mean_sec) * 100.0, 2)
        else:
            speedup_pct = 0.0

        passed_gate, recommendation, gate_details = self.evaluate_promotion_gate(
            candidate_report, regressions
        )

        comparison = ModelComparisonReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            baseline_model=baseline_report.model_name,
            candidate_model=candidate_report.model_name,
            tool_accuracy_delta=tool_acc_delta,
            param_fidelity_delta=param_fid_delta,
            security_adherence_delta=sec_adh_delta,
            overall_accuracy_delta=overall_acc_delta,
            mean_latency_delta_sec=mean_latency_delta,
            median_latency_delta_sec=median_latency_delta,
            speedup_pct=speedup_pct,
            regressions=regressions,
            passed_promotion_gate=passed_gate,
            recommendation=recommendation,
            gate_details=gate_details,
            candidate_summary={
                "model_name": candidate_report.model_name,
                "tool_accuracy_pct": candidate_report.tool_accuracy_pct,
                "param_fidelity_pct": candidate_report.param_fidelity_pct,
                "security_adherence_pct": candidate_report.security_adherence_pct,
                "mean_latency_sec": round(cand_mean_sec, 2),
                "passed_cases": candidate_report.passed_cases,
                "total_cases": candidate_report.total_cases,
            },
            baseline_summary={
                "model_name": baseline_report.model_name,
                "tool_accuracy_pct": baseline_report.tool_accuracy_pct,
                "param_fidelity_pct": baseline_report.param_fidelity_pct,
                "security_adherence_pct": baseline_report.security_adherence_pct,
                "mean_latency_sec": round(base_mean_sec, 2),
                "passed_cases": baseline_report.passed_cases,
                "total_cases": baseline_report.total_cases,
            },
        )
        return comparison

    def save_comparison_report(
        self, comparison: ModelComparisonReport, output_path: Union[str, Path]
    ) -> Path:
        """Persist comparison report to disk."""
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(comparison.model_dump_json(indent=2))
        return target
