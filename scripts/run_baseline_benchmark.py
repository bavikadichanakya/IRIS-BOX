import os
import json
import asyncio
import logging
from pathlib import Path

from src.agent.orchestrator import IRISOrchestrator
from src.eval.dataset import get_standard_benchmark_suite
from src.eval.replay_engine import ReplayEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("iris.eval.baseline")


async def main():
    print("=" * 70)
    print("IRIS EVALUATION HARNESS: Running Full Replay Benchmark Baseline (6 Domains)")
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

    # 2. Retrieve standard 6-tool-domain benchmark cases
    cases = get_standard_benchmark_suite()

    print(f"\nExecuting {len(cases)} benchmark cases across 6 tool domains against live Qwen 2.5 7B...")
    report = await engine.run_suite(cases, orchestrator)

    # 3. Persist standard baseline file
    baseline_path = reports_dir / "baseline_qwen2.5_7b.json"
    with open(baseline_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    print("\n" + "=" * 70)
    print("BENCHMARK BASELINE RESULTS (6 TOOL DOMAINS)")
    print("=" * 70)
    print(f"Total Cases:            {report.total_cases}")
    print(f"Passed Cases:           {report.passed_cases}")
    print(f"Failed Cases:           {report.failed_cases}")
    print(f"Overall Accuracy:       {report.accuracy_pct:.1f}%")
    print(f"Tool Selection Acc:     {report.tool_accuracy_pct:.1f}%")
    print(f"Parameter Fidelity:     {report.param_fidelity_pct:.1f}%")
    print(f"Security Adherence:     {report.security_adherence_pct:.1f}%")
    print(f"Mean Latency:           {report.mean_latency_sec:.2f}s ({report.avg_latency_ms:.1f} ms)")
    print(f"Median Latency:         {report.median_latency_sec:.2f}s ({report.median_latency_ms:.1f} ms)")
    print("-" * 70)
    for idx, r in enumerate(report.results, 1):
        status_icon = "PASS" if r.passed else "FAIL"
        print(
            f"[{status_icon}] Case {idx} ({r.case_id}): "
            f"Tool={r.tool_called} | Correct={r.tool_selection_correct} | "
            f"ParamsMatched={r.params_matched} | SecAdherent={r.security_adherent} | "
            f"Latency={r.latency_ms / 1000.0:.2f}s"
        )
        if r.error:
            print(f"       Error: {r.error}")
    print("=" * 70)
    print(f"Baseline report successfully written to: {baseline_path.resolve()}\n")


if __name__ == "__main__":
    asyncio.run(main())
