import os
import json
import asyncio
import logging
from pathlib import Path

from src.agent.orchestrator import IRISOrchestrator
from src.eval.models import TaskBenchmarkCase
from src.eval.replay_engine import ReplayEngine
from src.tools.capability import PermissionLevel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("iris.eval.baseline")


async def main():
    print("=" * 70)
    print("IRIS EVALUATION HARNESS: Running Full Replay Benchmark Baseline")
    print("Model: qwen2.5:7b-instruct | Endpoint: http://localhost:11434/v1")
    print("=" * 70)

    # 1. Initialize Orchestrator with local Qwen 2.5 7B
    orchestrator = IRISOrchestrator(
        api_base="http://localhost:11434/v1",
        api_key="ollama",
        model="qwen2.5:7b-instruct",
    )

    reports_dir = Path("data/eval_reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    engine = ReplayEngine(reports_dir=str(reports_dir))

    # 2. Define standard benchmark cases covering core intents + operator
    cases = [
        TaskBenchmarkCase(
            id="smart_home_lights",
            case_id="smart_home_lights",
            user_prompt="Turn off the living room lights",
            expected_tool="HomeAssistantTool",
            expected_permission="PROTECTED",
            expected_params_subset={"action": "off", "domain": "light"},
            ground_truth_tokens=["lights", "off"],
        ),
        TaskBenchmarkCase(
            id="system_terminal_echo",
            case_id="system_terminal_echo",
            user_prompt="Create an execution plan to echo hello and dir",
            expected_tool="SystemCommandTool",
            expected_permission="SENSITIVE",
            expected_params_subset={"command": "echo hello"},
            ground_truth_tokens=["hello"],
        ),
        TaskBenchmarkCase(
            id="browser_navigation",
            case_id="browser_navigation",
            user_prompt="Open https://github.com in the browser",
            expected_tool="BrowserActionTool",
            expected_permission="PUBLIC",
            expected_params_subset={"action": "navigate"},
            ground_truth_tokens=["github.com"],
        ),
        TaskBenchmarkCase(
            id="operator_workspace_diagnosis",
            case_id="operator_workspace_diagnosis",
            user_prompt="Check why tests are failing in my current project",
            expected_tool="ProjectOperatorTool",
            expected_permission="SENSITIVE",
            expected_params_subset={"action": "diagnose"},
            ground_truth_tokens=["diagnose", "test"],
        ),
    ]

    print(f"\nExecuting {len(cases)} benchmark cases against live Qwen 2.5 7B...")
    report = await engine.run_suite(cases, orchestrator)

    # 3. Persist standard baseline file
    baseline_path = reports_dir / "baseline_qwen2.5_7b.json"
    with open(baseline_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    print("\n" + "=" * 70)
    print("BENCHMARK BASELINE RESULTS")
    print("=" * 70)
    print(f"Total Cases:            {report.total_cases}")
    print(f"Passed Cases:           {report.passed_cases}")
    print(f"Failed Cases:           {report.failed_cases}")
    print(f"Overall Accuracy:       {report.accuracy_pct:.1f}%")
    print(f"Tool Selection Acc:     {report.tool_accuracy_pct:.1f}%")
    print(f"Parameter Fidelity:     {report.param_fidelity_pct:.1f}%")
    print(f"Security Adherence:     {report.security_adherence_pct:.1f}%")
    print(f"Average Latency:        {report.avg_latency_ms:.1f} ms")
    print("-" * 70)
    for idx, r in enumerate(report.results, 1):
        status_icon = "PASS" if r.passed else "FAIL"
        print(f"[{status_icon}] Case {idx} ({r.case_id}): Tool={r.tool_called} | Correct={r.tool_selection_correct} | Matched={r.params_matched} | Latency={r.latency_ms:.1f}ms")
        if r.error:
            print(f"       Error: {r.error}")
    print("=" * 70)
    print(f"Baseline report successfully written to: {baseline_path.resolve()}\n")


if __name__ == "__main__":
    asyncio.run(main())
