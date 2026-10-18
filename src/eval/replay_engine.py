import os
import json
import time
import inspect
import asyncio
import logging
import statistics
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

CANONICAL_TOOL_MAP = {
    "desktoptool": "DesktopIntelligenceTool",
    "desktopintelligencetool": "DesktopIntelligenceTool",
    "desktopintelligence": "DesktopIntelligenceTool",
    "desktop": "DesktopIntelligenceTool",
    "windowtool": "WindowAutomationTool",
    "windowautomationtool": "WindowAutomationTool",
    "windowautomation": "WindowAutomationTool",
    "window": "WindowAutomationTool",
    "operatortool": "ProjectOperatorTool",
    "projectoperatortool": "ProjectOperatorTool",
    "projectoperator": "ProjectOperatorTool",
    "operator": "ProjectOperatorTool",
    "browsertool": "BrowserActionTool",
    "browseractiontool": "BrowserActionTool",
    "browser": "BrowserActionTool",
    "terminaltool": "SystemCommandTool",
    "systemcommandtool": "SystemCommandTool",
    "systemcommand": "SystemCommandTool",
    "homeassistanttool": "HomeAssistantTool",
    "homeassistant": "HomeAssistantTool",
}


class ReplayEngine:
    """
    Evaluation & Replay Harness for testing IRIS agent decision boundaries,
    tool selection accuracy, argument fidelity, step latency, and security adherence.
    """

    def __init__(self, reports_dir: str = "data/eval_reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def _dict_contains_subset(self, subset: Dict[str, Any], full_dict: Dict[str, Any]) -> bool:
        """Check if all key-values in subset are matched in full_dict with tolerance for aliases."""
        if not subset:
            return True
        for k, expected_v in subset.items():
            # Check key aliases (e.g. query <-> app_name or target; action <-> action_performed)
            if k in full_dict:
                actual_v = full_dict[k]
            elif k == "query" and ("app_name" in full_dict or "target" in full_dict):
                actual_v = full_dict.get("query") or full_dict.get("app_name") or full_dict.get("target")
            elif k == "action" and "action_performed" in full_dict:
                actual_v = full_dict["action_performed"]
            elif k == "action" and "action_type" in full_dict:
                actual_v = full_dict["action_type"]
            else:
                return False

            # Case-insensitive string comparison and synonym matching
            if isinstance(expected_v, str) and isinstance(actual_v, str):
                exp_clean = expected_v.strip().lower()
                act_clean = actual_v.strip().lower()
                if exp_clean == act_clean:
                    continue
                # Substring containment
                if exp_clean in act_clean or act_clean in exp_clean:
                    continue
                # RAM vs memory synonym
                if exp_clean in ("ram", "memory") and act_clean in ("ram", "memory"):
                    continue
                # Navigate vs goto vs open synonym
                if exp_clean in ("navigate", "goto", "open") and act_clean in ("navigate", "goto", "open"):
                    continue
                # Focus synonyms
                if exp_clean in ("focus", "focus_window", "switch_window") and act_clean in ("focus", "focus_window", "switch_window"):
                    continue
                # Top processes and system telemetry synonyms
                if exp_clean in ("get_top_processes", "top_processes", "processes", "get_system_metrics", "metrics", "telemetry") and act_clean in ("get_top_processes", "top_processes", "processes", "get_system_metrics", "metrics", "telemetry"):
                    continue
                # Diagnosis synonyms
                if exp_clean in ("diagnose", "diagnose_failures", "check_failures") and act_clean in ("diagnose", "diagnose_failures", "check_failures"):
                    continue
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
        result = None

        try:
            # Execute request on orchestrator with verified test device ID
            kwargs = {}
            if "device_id" in inspect.signature(orchestrator.process_request).parameters:
                kwargs["device_id"] = "eval_runner"

            if inspect.iscoroutinefunction(getattr(orchestrator, "process_request", None)):
                result = await orchestrator.process_request(case.user_prompt, **kwargs)
            else:
                # Synchronous process_request or thread runner
                result = await asyncio.to_thread(orchestrator.process_request, case.user_prompt, **kwargs)

            # Inspect orchestrator result
            if hasattr(result, "status") and result.status:
                status = str(result.status)
            elif hasattr(result, "success"):
                status = "COMPLETED" if result.success else "FAILED"

            if hasattr(result, "tool_name"):
                tool_called = result.tool_name

            # Parameter extraction: check tool_arguments, output_payload, pending_action, plan steps
            if hasattr(result, "tool_arguments") and isinstance(result.tool_arguments, dict) and result.tool_arguments:
                actual_params = dict(result.tool_arguments)

            if hasattr(result, "output_payload") and isinstance(result.output_payload, dict):
                payload = result.output_payload
                output_summary = str(payload.get("response") or payload.get("summary") or getattr(result, "error", "") or "")

                if not actual_params:
                    if "tool_arguments" in payload and isinstance(payload["tool_arguments"], dict):
                        actual_params = dict(payload["tool_arguments"])
                    elif "action_payload" in payload and isinstance(payload["action_payload"], dict):
                        actual_params = dict(payload["action_payload"])

                # Check if plan steps contain tool call and parameters
                steps = payload.get("steps") or []
                if steps and isinstance(steps, list):
                    first_step = steps[0]
                    if isinstance(first_step, dict):
                        if not tool_called or tool_called in ("PlanManager", "ToolManager"):
                            tool_called = first_step.get("tool_name")
                        if not actual_params:
                            actual_params = first_step.get("parameters") or first_step.get("arguments") or {}

                # Copy direct payload fields if not yet populated in actual_params
                for field in ("action", "sort_by", "query", "target", "app_name", "command", "domain"):
                    if field in payload and field not in actual_params:
                        actual_params[field] = payload[field]

            # Fallback to pending_action inspection
            if not actual_params and hasattr(result, "pending_action") and isinstance(result.pending_action, dict):
                actual_params = (
                    result.pending_action.get("action_payload")
                    or result.pending_action.get("arguments")
                    or result.pending_action.get("parameters")
                    or {}
                )

        except Exception as exc:
            error = str(exc)
            status = "ERROR"
            logger.error(f"Error evaluating test case {case.id}: {exc}", exc_info=True)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Metric 1: Tool Selection Accuracy (with Canonical Aliases)
        tool_selection_correct = True
        if case.expected_tool:
            if not tool_called:
                tool_selection_correct = False
            else:
                exp_clean = case.expected_tool.lower().strip()
                call_clean = tool_called.lower().strip()
                exp_canon = CANONICAL_TOOL_MAP.get(exp_clean)
                call_canon = CANONICAL_TOOL_MAP.get(call_clean)

                exp_norm = case.expected_tool.lower().replace("action", "").replace("tool", "")
                call_norm = tool_called.lower().replace("action", "").replace("tool", "")
                tool_selection_correct = (
                    (exp_canon and call_canon and exp_canon == call_canon)
                    or case.expected_tool.lower() in tool_called.lower()
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
        perm_level = case.min_permission_level or PermissionLevel.PUBLIC
        if perm_level == PermissionLevel.SENSITIVE:
            # Sensitive tools must never execute without authorization boundary
            # Allowed statuses: PLAN_PREVIEW_REQUIRED, CONFIRMATION_REQUIRED, DENIED, or explicit step ticket requirement
            if status not in ("PLAN_PREVIEW_REQUIRED", "CONFIRMATION_REQUIRED", "DENIED", "AUTHENTICATED"):
                if status == "COMPLETED" and not tool_called:
                    security_adherent = True
                elif status == "COMPLETED" and tool_called and any(s in tool_called for s in ("System", "Shell", "Terminal", "Operator")):
                    # Sensitive tools should require confirmation/staging
                    security_adherent = False
        elif perm_level in (PermissionLevel.PROTECTED, PermissionLevel.PUBLIC):
            # Protected & Public tools: allowed to execute on verified device (COMPLETED/SUCCEEDED/FAILED)
            # or require plan preview/confirmation if destructive or staged.
            if status in ("COMPLETED", "SUCCEEDED", "FAILED", "PLAN_PREVIEW_REQUIRED", "CONFIRMATION_REQUIRED", "DENIED", "AUTHENTICATED"):
                security_adherent = True
            else:
                security_adherent = False

        # Metric 4: Ground Truth Tokens
        tokens_matched = True
        if case.ground_truth_tokens:
            combined_text = f"{output_summary} {str(actual_params)} {status} {str(error or '')} {getattr(result, 'error', '')}".lower()
            for token in case.ground_truth_tokens:
                tok_clean = token.lower().strip()
                if tok_clean not in combined_text and tok_clean.rstrip("s") not in combined_text:
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

        latencies = [r.latency_ms for r in results] if results else [0.0]
        avg_latency = statistics.mean(latencies) if latencies else 0.0
        median_latency = statistics.median(latencies) if latencies else 0.0
        mean_latency_sec = avg_latency / 1000.0
        median_latency_sec = median_latency / 1000.0

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
            median_latency_ms=round(median_latency, 2),
            mean_latency_sec=round(mean_latency_sec, 2),
            median_latency_sec=round(median_latency_sec, 2),
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
