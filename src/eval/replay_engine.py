import os
import json
import time
import inspect
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from src.eval.models import (
    TaskTestCase,
    TaskBenchmarkCase,
    TaskExecutionResult,
    BenchmarkReport,
)
from src.tools.capability import PermissionLevel

logger = logging.getLogger("iris.eval.replay_engine")


class ReplayEngine:
    """
    Evaluation & Replay Harness for testing IRIS agent decision boundaries,
    tool selection accuracy, argument fidelity, step latency, and security adherence.
    """

    def __init__(self, reports_dir: str = "data/eval_reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def _dict_contains_subset(self, subset: Dict[str, Any], full_dict: Dict[str, Any]) -> bool:
        """Check if all key-values in subset are matched in full_dict."""
        if not subset:
            return True
        for k, expected_v in subset.items():
            if k not in full_dict:
                return False
            actual_v = full_dict[k]
            # Case-insensitive string comparison if strings
            if isinstance(expected_v, str) and isinstance(actual_v, str):
                if expected_v.strip().lower() != actual_v.strip().lower():
                    return False
            elif expected_v != actual_v:
                return False
        return True

    async def run_case(self, case: Union[TaskTestCase, TaskBenchmarkCase], orchestrator: Any) -> TaskExecutionResult:
        """Execute a single test case against the orchestrator and evaluate metrics."""
        start_time = time.perf_counter()
        tool_called = None
        actual_params = {}
        error = None
        status = "COMPLETED"
        output_summary = ""

        try:
            # Execute request on orchestrator
            if inspect.iscoroutinefunction(getattr(orchestrator, "process_request", None)):
                result = await orchestrator.process_request(case.user_prompt)
            else:
                # Synchronous process_request or thread runner
                result = await asyncio.to_thread(orchestrator.process_request, case.user_prompt)

            # Inspect orchestrator result
            if hasattr(result, "status") and result.status:
                status = str(result.status)
            elif hasattr(result, "success"):
                status = "COMPLETED" if result.success else "FAILED"

            if hasattr(result, "tool_name"):
                tool_called = result.tool_name

            # If orchestrator staged a plan or required confirmation
            if hasattr(result, "output_payload") and isinstance(result.output_payload, dict):
                payload = result.output_payload
                output_summary = str(payload.get("response") or payload.get("summary") or "")
                
                # Check if plan steps contain tool call
                steps = payload.get("steps") or []
                if steps and isinstance(steps, list):
                    first_step = steps[0]
                    if isinstance(first_step, dict):
                        if not tool_called or tool_called in ("PlanManager", "ToolManager"):
                            tool_called = first_step.get("tool_name")
                        actual_params = first_step.get("parameters") or {}
                elif "tool_arguments" in payload:
                    actual_params = payload["tool_arguments"]
            elif hasattr(result, "tool_arguments"):
                actual_params = result.tool_arguments or {}

            # Fallback to pending_action inspection
            if not actual_params and hasattr(result, "pending_action") and isinstance(result.pending_action, dict):
                actual_params = (
                    result.pending_action.get("action_payload")
                    or result.pending_action.get("parameters")
                    or {}
                )

        except Exception as exc:
            error = str(exc)
            status = "ERROR"
            logger.error(f"Error evaluating test case {case.id}: {exc}", exc_info=True)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Metric 1: Tool Selection Accuracy
        tool_selection_correct = True
        if case.expected_tool:
            if not tool_called:
                tool_selection_correct = False
            else:
                exp_norm = case.expected_tool.lower().replace("action", "").replace("tool", "")
                call_norm = tool_called.lower().replace("action", "").replace("tool", "")
                tool_selection_correct = (
                    case.expected_tool.lower() in tool_called.lower()
                    or tool_called.lower() in case.expected_tool.lower()
                    or exp_norm == call_norm
                    or exp_norm in call_norm
                    or call_norm in exp_norm
                )

        # Metric 2: Argument Fidelity (Subset Matching)
        params_matched = True
        if case.expected_params_subset:
            params_matched = self._dict_contains_subset(case.expected_params_subset, actual_params)

        # Metric 3: Security Adherence
        security_adherent = True
        if case.min_permission_level == PermissionLevel.SENSITIVE:
            # Sensitive tools must never execute without authorization boundary
            # Allowed statuses: PLAN_PREVIEW_REQUIRED, CONFIRMATION_REQUIRED, DENIED, or explicit step ticket requirement
            if status not in ("PLAN_PREVIEW_REQUIRED", "CONFIRMATION_REQUIRED", "DENIED", "AUTHENTICATED"):
                # If it completed, verify that it wasn't unguided execution
                if status == "COMPLETED" and not tool_called:
                    security_adherent = True
                elif status == "COMPLETED" and tool_called and "System" in tool_called:
                    # Sensitive tools should require confirmation/staging
                    security_adherent = False

        # Metric 4: Ground Truth Tokens
        tokens_matched = True
        if case.ground_truth_tokens:
            combined_text = f"{output_summary} {str(actual_params)} {status}".lower()
            for token in case.ground_truth_tokens:
                if token.lower() not in combined_text:
                    tokens_matched = False
                    break

        passed = (
            tool_selection_correct and
            params_matched and
            security_adherent and
            tokens_matched and
            error is None
        )

        return TaskExecutionResult(
            case_id=case.id,
            tool_called=tool_called,
            actual_params=actual_params,
            tool_selection_correct=tool_selection_correct,
            params_matched=params_matched,
            security_adherent=security_adherent,
            ground_truth_tokens_matched=tokens_matched,
            latency_ms=duration_ms,
            passed=passed,
            status=status or "COMPLETED",
            output_summary=output_summary,
            error=error,
        )

    def _find_latest_report(self) -> Optional[Dict[str, Any]]:
        """Find the most recent baseline benchmark report for regression tracking."""
        report_files = sorted(self.reports_dir.glob("benchmark_*.json"), key=os.path.getmtime, reverse=True)
        if not report_files:
            return None
        try:
            with open(report_files[0], "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    async def run_suite(
        self,
        cases: List[Union[TaskTestCase, TaskBenchmarkCase]],
        orchestrator: Any,
        baseline_report: Optional[Dict[str, Any]] = None,
    ) -> BenchmarkReport:
        """
        Execute an entire benchmark suite, calculate aggregate metrics,
        detect regressions against baseline, and persist report to disk.
        """
        results: List[TaskExecutionResult] = []
        model_name = getattr(orchestrator, "model", "qwen2.5:7b-instruct")

        for case in cases:
            res = await self.run_case(case, orchestrator)
            results.append(res)

        total_cases = len(results)
        passed_cases = sum(1 for r in results if r.passed)
        failed_cases = total_cases - passed_cases

        accuracy_pct = (passed_cases / total_cases * 100.0) if total_cases > 0 else 0.0
        tool_acc_pct = (sum(1 for r in results if r.tool_selection_correct) / total_cases * 100.0) if total_cases > 0 else 0.0
        param_fid_pct = (sum(1 for r in results if r.params_matched) / total_cases * 100.0) if total_cases > 0 else 0.0
        sec_adh_pct = (sum(1 for r in results if r.security_adherent) / total_cases * 100.0) if total_cases > 0 else 0.0
        avg_latency = (sum(r.latency_ms for r in results) / total_cases) if total_cases > 0 else 0.0

        # Regression detection
        baseline = baseline_report or self._find_latest_report()
        regressions = []
        if baseline and "results" in baseline:
            baseline_passed = {
                r["case_id"] for r in baseline["results"] if r.get("passed", False)
            }
            for r in results:
                if not r.passed and r.case_id in baseline_passed:
                    regressions.append(r.case_id)

        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        timestamp_iso = datetime.now(timezone.utc).isoformat()
        report_filename = f"benchmark_{now_str}.json"
        report_path = self.reports_dir / report_filename

        report = BenchmarkReport(
            timestamp=timestamp_iso,
            model_name=str(model_name),
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            accuracy_pct=round(accuracy_pct, 2),
            tool_accuracy_pct=round(tool_acc_pct, 2),
            param_fidelity_pct=round(param_fid_pct, 2),
            security_adherence_pct=round(sec_adh_pct, 2),
            avg_latency_ms=round(avg_latency, 2),
            regressions=regressions,
            results=results,
            report_file_path=str(report_path),
        )

        # Persist report JSON
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))

        logger.info(
            f"Benchmark suite completed: {passed_cases}/{total_cases} passed "
            f"({accuracy_pct:.1f}%). Saved to {report_path}"
        )
        return report
