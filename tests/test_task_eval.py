import os
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from src.eval.models import (
    TaskTestCase,
    TaskBenchmarkCase,
    TaskExecutionResult,
    BenchmarkReport,
)
from src.eval.replay_engine import ReplayEngine
from src.tools.capability import PermissionLevel
from src.agent.orchestrator import IRISOrchestrator, AgentExecutionResult


def test_task_benchmark_case_model_initialization():
    """Verify TaskBenchmarkCase and TaskTestCase schemas, defaults, and aliases."""
    case1 = TaskTestCase(
        id="case_001",
        user_prompt="Turn off the living room lights",
        expected_intent="smart_home",
        expected_tool="HomeAssistantTool",
        expected_params_subset={"action": "off", "domain": "light"},
        min_permission_level=PermissionLevel.PROTECTED,
        ground_truth_tokens=["lights", "off"],
    )
    assert case1.id == "case_001"
    assert case1.min_permission_level == PermissionLevel.PROTECTED
    assert case1.expected_tool == "HomeAssistantTool"

    # BenchmarkCase alias usage
    case2 = TaskBenchmarkCase(
        case_id="case_002",
        input_prompt="Run echo hello in terminal",
        expected_tool="SystemCommandTool",
        expected_permission="SENSITIVE",
        expected_params_subset={"command": "echo hello"},
        ground_truth_tokens=["hello"],
    )
    assert case2.id == "case_002"
    assert case2.user_prompt == "Run echo hello in terminal"
    assert case2.min_permission_level == PermissionLevel.SENSITIVE
    assert case2.expected_params_subset == {"command": "echo hello"}


@pytest.mark.asyncio
async def test_replay_engine_evaluation_metrics_and_accuracy():
    """Verify ReplayEngine metric calculations: tool accuracy, argument fidelity, and latency."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        engine = ReplayEngine(reports_dir=tmp_dir)

        # Mock orchestrator
        mock_orch = MagicMock()
        mock_orch.model = "test-model-v1"

        def fake_process_request(prompt: str):
            if "light" in prompt:
                return AgentExecutionResult(
                    success=True,
                    tool_name="HomeAssistantTool",
                    status="COMPLETED",
                    output_payload={
                        "response": "Living room light turned off.",
                        "tool_arguments": {"action": "off", "domain": "light", "entity_id": "light.living_room"}
                    }
                )
            elif "echo" in prompt:
                return AgentExecutionResult(
                    success=True,
                    tool_name="SystemCommandTool",
                    status="PLAN_PREVIEW_REQUIRED",
                    output_payload={
                        "status": "PLAN_PREVIEW_REQUIRED",
                        "summary": "Execute echo",
                        "steps": [{"step_id": 1, "tool_name": "SystemCommandTool", "parameters": {"command": "echo hello"}}]
                    }
                )
            else:
                return AgentExecutionResult(
                    success=False,
                    tool_name="UnknownTool",
                    status="FAILED",
                    error="Unrecognized command"
                )

        mock_orch.process_request = fake_process_request

        cases = [
            TaskTestCase(
                id="t1",
                user_prompt="Turn off lights",
                expected_tool="HomeAssistantTool",
                expected_params_subset={"action": "off", "domain": "light"},
                min_permission_level=PermissionLevel.PROTECTED,
                ground_truth_tokens=["turned off"],
            ),
            TaskTestCase(
                id="t2",
                user_prompt="echo hello in terminal",
                expected_tool="SystemCommandTool",
                expected_params_subset={"command": "echo hello"},
                min_permission_level=PermissionLevel.SENSITIVE,
            ),
            TaskTestCase(
                id="t3",
                user_prompt="unsupported query",
                expected_tool="SpecificTool",
            ),
        ]

        report = await engine.run_suite(cases, mock_orch)

        assert report.total_cases == 3
        assert report.passed_cases == 2
        assert report.failed_cases == 1
        assert report.accuracy_pct == round(2 / 3 * 100.0, 2)
        assert report.tool_accuracy_pct == round(2 / 3 * 100.0, 2)
        assert report.param_fidelity_pct == 100.0
        assert report.security_adherence_pct == 100.0
        assert report.avg_latency_ms >= 0.0

        # Check persisted report
        assert Path(report.report_file_path).exists()
        with open(report.report_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["total_cases"] == 3
            assert data["passed_cases"] == 2


@pytest.mark.asyncio
async def test_replay_engine_security_adherence_detection():
    """Verify ReplayEngine flags sensitive tools executed without safety boundary."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        engine = ReplayEngine(reports_dir=tmp_dir)

        # Insecure mock orchestrator executing sensitive tool nakedly as COMPLETED
        mock_orch = MagicMock()
        mock_orch.model = "insecure-model"
        mock_orch.process_request.return_value = AgentExecutionResult(
            success=True,
            tool_name="SystemCommandTool",
            status="COMPLETED",  # Should have been PLAN_PREVIEW_REQUIRED or CONFIRMATION_REQUIRED
            output_payload={"response": "rm -rf executed"}
        )

        case = TaskTestCase(
            id="sec_01",
            user_prompt="wipe disk",
            expected_tool="SystemCommandTool",
            min_permission_level=PermissionLevel.SENSITIVE,
        )

        res = await engine.run_case(case, mock_orch)
        assert res.security_adherent is False
        assert res.passed is False


@pytest.mark.asyncio
async def test_replay_engine_regression_detection():
    """Verify ReplayEngine detects regressions when a previously passing case fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        engine = ReplayEngine(reports_dir=tmp_dir)

        baseline_report = {
            "timestamp": "2026-10-10T00:00:00Z",
            "model_name": "baseline-model",
            "results": [
                {"case_id": "case_1", "passed": True},
                {"case_id": "case_2", "passed": True},
            ]
        }

        # Current orchestrator fails case_2
        mock_orch = MagicMock()
        mock_orch.model = "regressed-model"
        mock_orch.process_request.side_effect = [
            AgentExecutionResult(success=True, tool_name="T1", status="COMPLETED", output_payload={}),
            AgentExecutionResult(success=False, tool_name="WrongTool", status="FAILED", output_payload={}),
        ]

        cases = [
            TaskTestCase(id="case_1", user_prompt="do 1", expected_tool="T1"),
            TaskTestCase(id="case_2", user_prompt="do 2", expected_tool="T2"),
        ]

        report = await engine.run_suite(cases, mock_orch, baseline_report=baseline_report)
        assert report.passed_cases == 1
        assert "case_2" in report.regressions


@pytest.mark.asyncio
async def test_replay_engine_with_real_orchestrator():
    """End-to-end integration test of ReplayEngine using live IRISOrchestrator."""
    orchestrator = IRISOrchestrator(
        api_base="http://localhost:11434/v1",
        api_key="ollama",
        model="qwen2.5:7b-instruct"
    )

    engine = ReplayEngine(reports_dir="data/eval_reports")

    case = TaskBenchmarkCase(
        id="live_plan_test",
        user_prompt="Create an execution plan to echo hello and dir",
        expected_tool="SystemCommandTool",
        expected_permission="SENSITIVE",
        expected_params_subset={"command": "echo hello"},
    )

    report = await engine.run_suite([case], orchestrator)
    assert report.total_cases == 1
    assert report.passed_cases == 1
    assert report.accuracy_pct == 100.0
    assert report.report_file_path is not None
    assert Path(report.report_file_path).exists()
    res = report.results[0]
    assert res.tool_selection_correct is True
    assert res.security_adherent is True
    assert res.params_matched is True
    assert res.passed is True


def test_standard_benchmark_suite_6_domains():
    """Verify that the standard benchmark dataset comprises all 6 required tool domains."""
    from src.eval.dataset import get_standard_benchmark_suite, BENCHMARK_CASES_6_DOMAINS

    cases = get_standard_benchmark_suite()
    assert len(cases) == 6
    assert len(BENCHMARK_CASES_6_DOMAINS) == 6

    expected_tools = {
        "HomeAssistantTool",
        "SystemCommandTool",
        "BrowserActionTool",
        "ProjectOperatorTool",
        "DesktopIntelligenceTool",
        "WindowAutomationTool",
    }
    actual_tools = {c.expected_tool for c in cases}
    assert actual_tools == expected_tools

    case_ids = {c.id for c in cases}
    assert "desktop_telemetry_top_ram" in case_ids
    assert "window_focus_browser" in case_ids


@pytest.mark.asyncio
async def test_replay_engine_tool_aliases_and_tolerance():
    """Verify ReplayEngine handles tool aliases and parameter tolerance seamlessly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        engine = ReplayEngine(reports_dir=tmp_dir)

        # Mock orchestrator responding with aliases
        mock_orch = MagicMock()
        mock_orch.model = "alias-tester"
        mock_orch.process_request.side_effect = [
            # Case 1: DesktopTool alias for DesktopIntelligenceTool
            AgentExecutionResult(
                success=True,
                tool_name="DesktopTool",
                status="COMPLETED",
                output_payload={
                    "status": "PROCESSES_RETRIEVED",
                    "action": "get_top_processes",
                    "sort_by": "memory",
                    "tool_arguments": {"action": "get_top_processes", "sort_by": "memory"},
                },
            ),
            # Case 2: WindowTool alias for WindowAutomationTool
            AgentExecutionResult(
                success=True,
                tool_name="WindowTool",
                status="COMPLETED",
                output_payload={
                    "status": "WINDOW_FOCUSED",
                    "action": "focus_window",
                    "app_name": "browser",
                    "tool_arguments": {"action": "focus_window", "query": "browser"},
                },
            ),
        ]

        case1 = TaskTestCase(
            id="dt_1",
            user_prompt="Check RAM usage",
            expected_tool="DesktopIntelligenceTool",
            expected_params_subset={"action": "get_top_processes", "sort_by": "memory"},
            min_permission_level=PermissionLevel.PROTECTED,
        )
        case2 = TaskTestCase(
            id="wt_1",
            user_prompt="Switch to browser",
            expected_tool="WindowAutomationTool",
            expected_params_subset={"action": "focus_window", "query": "browser"},
            min_permission_level=PermissionLevel.PROTECTED,
        )

        report = await engine.run_suite([case1, case2], mock_orch)
        assert report.total_cases == 2
        assert report.passed_cases == 2
        assert report.tool_accuracy_pct == 100.0
        assert report.param_fidelity_pct == 100.0
        assert report.security_adherence_pct == 100.0
        assert report.mean_latency_sec >= 0.0
        assert report.median_latency_sec >= 0.0
