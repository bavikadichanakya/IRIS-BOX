"""
Unit Tests for ModelComparator & Promotion Gate Engine.
Validates metric delta calculations, regression detection, and promotion gating policies.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.eval.comparator import ModelComparator, ModelComparisonReport
from src.eval.models import BenchmarkReport, TaskExecutionResult


@pytest.fixture
def baseline_report() -> BenchmarkReport:
    """Fixture providing a standard 6-case baseline report."""
    return BenchmarkReport(
        timestamp="2026-10-18T08:00:00Z",
        model_name="qwen2.5:7b-instruct",
        total_cases=6,
        passed_cases=6,
        failed_cases=0,
        accuracy_pct=100.0,
        tool_accuracy_pct=100.0,
        param_fidelity_pct=100.0,
        security_adherence_pct=100.0,
        avg_latency_ms=2000.0,
        median_latency_ms=1800.0,
        mean_latency_sec=2.0,
        median_latency_sec=1.8,
        regressions=[],
        results=[
            TaskExecutionResult(case_id="case_1", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=2000.0),
            TaskExecutionResult(case_id="case_2", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=1900.0),
            TaskExecutionResult(case_id="case_3", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=2100.0),
            TaskExecutionResult(case_id="case_4", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=1800.0),
            TaskExecutionResult(case_id="case_5", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=2200.0),
            TaskExecutionResult(case_id="case_6", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=2000.0),
        ],
    )


def test_comparator_promotion_gate_passed(baseline_report: BenchmarkReport):
    """Candidate with 100% accuracy, 100% security, 0 regressions, and lower latency passes gate."""
    candidate_report = BenchmarkReport(
        timestamp="2026-10-18T12:00:00Z",
        model_name="heretic-iris:latest",
        total_cases=6,
        passed_cases=6,
        failed_cases=0,
        accuracy_pct=100.0,
        tool_accuracy_pct=100.0,
        param_fidelity_pct=100.0,
        security_adherence_pct=100.0,
        avg_latency_ms=1500.0,
        median_latency_ms=1400.0,
        mean_latency_sec=1.5,
        median_latency_sec=1.4,
        regressions=[],
        results=[
            TaskExecutionResult(case_id="case_1", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=1500.0),
            TaskExecutionResult(case_id="case_2", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=1400.0),
            TaskExecutionResult(case_id="case_3", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=1600.0),
            TaskExecutionResult(case_id="case_4", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=1300.0),
            TaskExecutionResult(case_id="case_5", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=1700.0),
            TaskExecutionResult(case_id="case_6", tool_selection_correct=True, params_matched=True, security_adherent=True, passed=True, latency_ms=1500.0),
        ],
    )

    comparator = ModelComparator()
    comparison = comparator.compare(candidate=candidate_report, baseline=baseline_report)

    assert comparison.passed_promotion_gate is True
    assert comparison.recommendation == "PROMOTE_CANDIDATE"
    assert len(comparison.regressions) == 0
    assert comparison.tool_accuracy_delta == 0.0
    assert comparison.mean_latency_delta_sec == -0.5
    assert comparison.speedup_pct == 25.0  # (2.0 - 1.5)/2.0 = 25% faster


def test_comparator_promotion_gate_fails_on_regression(baseline_report: BenchmarkReport):
    """Candidate with tool regression fails the promotion gate and triggers rollback recommendation."""
    candidate_report = BenchmarkReport(
        timestamp="2026-10-18T12:00:00Z",
        model_name="failing-candidate:latest",
        total_cases=6,
        passed_cases=5,
        failed_cases=1,
        accuracy_pct=83.33,
        tool_accuracy_pct=83.33,
        param_fidelity_pct=100.0,
        security_adherence_pct=100.0,
        avg_latency_ms=1200.0,
        mean_latency_sec=1.2,
        results=[
            TaskExecutionResult(case_id="case_1", tool_selection_correct=True, passed=True),
            TaskExecutionResult(case_id="case_2", tool_selection_correct=False, passed=False),  # Regression
            TaskExecutionResult(case_id="case_3", tool_selection_correct=True, passed=True),
            TaskExecutionResult(case_id="case_4", tool_selection_correct=True, passed=True),
            TaskExecutionResult(case_id="case_5", tool_selection_correct=True, passed=True),
            TaskExecutionResult(case_id="case_6", tool_selection_correct=True, passed=True),
        ],
    )

    comparator = ModelComparator()
    comparison = comparator.compare(candidate=candidate_report, baseline=baseline_report)

    assert comparison.passed_promotion_gate is False
    assert comparison.recommendation == "RETAIN_ROLLBACK_BASELINE (qwen2.5:7b-instruct)"
    assert "case_2" in comparison.regressions
    assert len(comparison.regressions) == 1


def test_comparator_promotion_gate_fails_on_security_violation(baseline_report: BenchmarkReport):
    """Candidate with security adherence violation is rejected."""
    candidate_report = BenchmarkReport(
        timestamp="2026-10-18T12:00:00Z",
        model_name="insecure-candidate:latest",
        total_cases=6,
        passed_cases=6,
        failed_cases=0,
        accuracy_pct=100.0,
        tool_accuracy_pct=100.0,
        param_fidelity_pct=100.0,
        security_adherence_pct=83.33,  # Security failure
        avg_latency_ms=1000.0,
        mean_latency_sec=1.0,
        results=[
            TaskExecutionResult(case_id="case_1", tool_selection_correct=True, security_adherent=True, passed=True),
            TaskExecutionResult(case_id="case_2", tool_selection_correct=True, security_adherent=False, passed=True),
            TaskExecutionResult(case_id="case_3", tool_selection_correct=True, security_adherent=True, passed=True),
            TaskExecutionResult(case_id="case_4", tool_selection_correct=True, security_adherent=True, passed=True),
            TaskExecutionResult(case_id="case_5", tool_selection_correct=True, security_adherent=True, passed=True),
            TaskExecutionResult(case_id="case_6", tool_selection_correct=True, security_adherent=True, passed=True),
        ],
    )

    comparator = ModelComparator()
    comparison = comparator.compare(candidate=candidate_report, baseline=baseline_report)

    assert comparison.passed_promotion_gate is False
    assert comparison.recommendation == "RETAIN_ROLLBACK_BASELINE (qwen2.5:7b-instruct)"
    assert comparison.gate_details["security_adherence_check"]["passed"] is False


def test_comparator_loads_from_file_and_persists(tmp_path: Path, baseline_report: BenchmarkReport):
    """Verify loading from disk and persisting comparison JSON."""
    baseline_file = tmp_path / "test_baseline.json"
    candidate_file = tmp_path / "test_candidate.json"
    output_file = tmp_path / "test_comparison.json"

    baseline_file.write_text(baseline_report.model_dump_json(indent=2), encoding="utf-8")
    candidate_file.write_text(baseline_report.model_dump_json(indent=2), encoding="utf-8")

    comparator = ModelComparator(baseline_path=baseline_file)
    comparison = comparator.compare(candidate=candidate_file)

    assert comparison.passed_promotion_gate is True
    comparator.save_comparison_report(comparison, output_file)
    assert output_file.exists()

    with open(output_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["passed_promotion_gate"] is True
    assert loaded["recommendation"] == "PROMOTE_CANDIDATE"


def test_orchestrator_parses_double_braced_tool_calls():
    """Verify that orchestrator properly parses double-braced and escaped tool call outputs."""
    from src.agent.orchestrator import parse_fallback_tool_call, IRISOrchestrator

    # 1. Exact double-brace pattern from candidate model output
    raw_double_brace = '"{{\\"name\\": \\"HomeAssistantTool\\", \\"arguments\\": {{\\"action\\": \\"off\\", \\"domain\\": \\"light\\"}}}}"'
    tool_name, raw_args = parse_fallback_tool_call(raw_double_brace)

    assert tool_name == "HomeAssistantTool"
    args_dict = json.loads(raw_args)
    assert args_dict.get("action") == "off"
    assert args_dict.get("domain") == "light"

    # 2. Asymmetric braces with escaped quotes
    raw_mixed_brace = '"{{\\"name\\": \\"ProjectOperatorTool\\", \\"arguments\\": {\\"action\\": \\"diagnose_failures\\"}}}"'
    tool_name_mixed, raw_args_mixed = parse_fallback_tool_call(raw_mixed_brace)

    assert tool_name_mixed == "ProjectOperatorTool"
    args_dict_mixed = json.loads(raw_args_mixed)
    assert args_dict_mixed.get("action") == "diagnose_failures"

    # 3. Via IRISOrchestrator instance method
    from src.tools.registry import ToolRegistry

    orchestrator = IRISOrchestrator(
        api_base="http://127.0.0.1:11434/v1",
        api_key="ollama",
        model="heretic-iris:latest",
        tool_registry=ToolRegistry
    )
    inst_tool, inst_args = orchestrator._parse_fallback_tool_call(raw_double_brace)
    assert inst_tool == "HomeAssistantTool"
    assert json.loads(inst_args)["action"] == "off"


def test_orchestrator_defaults_and_fallback_configuration(monkeypatch):
    """Verify IRISOrchestrator defaults to heretic-iris:latest and qwen2.5:7b-instruct fallback."""
    from src.agent.orchestrator import IRISOrchestrator
    from src.tools.registry import ToolRegistry

    # 1. Pure defaults (when env vars are not set)
    monkeypatch.delenv("IRIS_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("IRIS_FALLBACK_MODEL", raising=False)

    orch = IRISOrchestrator(
        api_base="http://127.0.0.1:11434/v1",
        api_key="ollama",
        tool_registry=ToolRegistry
    )
    assert orch.model == "heretic-iris:latest"
    assert orch.model_name == "heretic-iris:latest"
    assert orch.fallback_model == "qwen2.5:7b-instruct"
    assert orch.fallback_model_name == "qwen2.5:7b-instruct"

    # 2. Environment variable overrides
    monkeypatch.setenv("IRIS_LLM_MODEL", "env-model:latest")
    monkeypatch.setenv("IRIS_FALLBACK_MODEL", "env-fallback:latest")
    env_orch = IRISOrchestrator(
        api_base="http://127.0.0.1:11434/v1",
        api_key="ollama",
        tool_registry=ToolRegistry
    )
    assert env_orch.model == "env-model:latest"
    assert env_orch.fallback_model == "env-fallback:latest"

    # 3. Explicit custom constructor configuration (highest precedence)
    custom_orch = IRISOrchestrator(
        api_base="http://127.0.0.1:11434/v1",
        api_key="ollama",
        model_name="custom-candidate:latest",
        fallback_model_name="custom-fallback:latest",
        tool_registry=ToolRegistry
    )
    assert custom_orch.model == "custom-candidate:latest"
    assert custom_orch.model_name == "custom-candidate:latest"
    assert custom_orch.fallback_model == "custom-fallback:latest"
    assert custom_orch.fallback_model_name == "custom-fallback:latest"


def test_orchestrator_automatic_rollback_on_model_not_found(monkeypatch):
    """Verify that IRISOrchestrator transparently falls back to qwen2.5:7b-instruct if primary model tag is missing."""
    import unittest.mock
    import openai
    from src.agent.orchestrator import IRISOrchestrator
    from src.tools.registry import ToolRegistry

    orch = IRISOrchestrator(
        api_base="http://127.0.0.1:11434/v1",
        api_key="ollama",
        model="heretic-iris:latest",
        fallback_model="qwen2.5:7b-instruct",
        tool_registry=ToolRegistry
    )

    models_called = []

    def mock_create(model, messages, **kwargs):
        models_called.append(model)
        if model == "heretic-iris:latest":
            # Simulate Ollama 404 model not found
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status_code = 404
            raise openai.NotFoundError(
                message="model 'heretic-iris:latest' not found, try pulling it first",
                response=mock_resp,
                body={"error": "model 'heretic-iris:latest' not found"}
            )
        else:
            # Fallback model succeeds
            mock_choice = unittest.mock.MagicMock()
            mock_choice.message = unittest.mock.MagicMock(
                content="Fallback response from qwen2.5:7b-instruct",
                tool_calls=None,
                function_call=None
            )
            mock_result = unittest.mock.MagicMock()
            mock_result.choices = [mock_choice]
            return mock_result

    monkeypatch.setattr(orch.client.chat.completions, "create", mock_create)

    result = orch.process_request("What is the status of the workstation?")

    assert result.success is True
    assert "Fallback response from qwen2.5:7b-instruct" in result.output_payload.get("response", "")
    assert models_called == ["heretic-iris:latest", "qwen2.5:7b-instruct"]
    assert orch.model == "qwen2.5:7b-instruct"
    assert orch.model_name == "qwen2.5:7b-instruct"


