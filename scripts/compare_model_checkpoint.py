#!/usr/bin/env python3
"""
Model Comparison and Promotion Benchmark Runner
Evaluates candidate model checkpoints against the verified qwen2.5:7b-instruct baseline.
Enforces strict promotion gate criteria:
  - Tool Accuracy == 100.0%
  - Security Adherence == 100.0%
  - Zero Regressions (len(regressions) == 0)

Outputs:
  - data/eval_reports/candidate_heretic_iris.json
  - data/eval_reports/comparison_heretic_vs_baseline.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.agent.orchestrator import IRISOrchestrator
from src.eval.comparator import ModelComparator, ModelComparisonReport
from src.eval.dataset import get_standard_benchmark_suite
from src.eval.models import BenchmarkReport
from src.eval.replay_engine import ReplayEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("iris.eval.compare")


def print_banner(title: str, subtitle: str = "") -> None:
    width = 78
    print("\n" + "=" * width)
    print(f"  {title.center(width - 4)}")
    if subtitle:
        print(f"  {subtitle.center(width - 4)}")
    print("=" * width + "\n")


async def run_candidate_evaluation(
    model: str,
    endpoint: str,
    candidate_output: Path,
) -> BenchmarkReport:
    """Run full 6-domain replay benchmark against candidate model."""
    print(f"[*] Initializing IRISOrchestrator for candidate model '{model}' at '{endpoint}'...")
    orchestrator = IRISOrchestrator(
        api_base=endpoint,
        api_key="ollama",
        model=model,
    )

    reports_dir = candidate_output.parent
    reports_dir.mkdir(parents=True, exist_ok=True)
    engine = ReplayEngine(reports_dir=str(reports_dir))

    cases = get_standard_benchmark_suite()
    print(f"[*] Executing {len(cases)} canonical benchmark cases across 6 tool domains...\n")

    report = await engine.run_suite(cases, orchestrator)

    with open(candidate_output, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    print(f"[OK] Candidate benchmark report saved to: {candidate_output.resolve()}")
    return report


def display_comparison_summary(comparison: ModelComparisonReport) -> None:
    """Print high-visibility comparative table and gate decision."""
    print("\n" + "-" * 78)
    print("  MODEL BENCHMARK COMPARISON MATRIX (Candidate vs Baseline)")
    print("-" * 78)
    print(f"  Baseline Model : {comparison.baseline_model}")
    print(f"  Candidate Model: {comparison.candidate_model}")
    print("-" * 78)

    base = comparison.baseline_summary
    cand = comparison.candidate_summary

    fmt = "  {:<26} | {:<16} | {:<16} | {:<12}"
    print(fmt.format("Metric", "Baseline", "Candidate", "Delta"))
    print("  " + "-" * 74)

    print(
        fmt.format(
            "Tool Selection Accuracy",
            f"{base.get('tool_accuracy_pct', 0.0):.1f}%",
            f"{cand.get('tool_accuracy_pct', 0.0):.1f}%",
            f"{comparison.tool_accuracy_delta:+.1f}%",
        )
    )
    print(
        fmt.format(
            "Parameter Fidelity",
            f"{base.get('param_fidelity_pct', 0.0):.1f}%",
            f"{cand.get('param_fidelity_pct', 0.0):.1f}%",
            f"{comparison.param_fidelity_delta:+.1f}%",
        )
    )
    print(
        fmt.format(
            "Security Adherence",
            f"{base.get('security_adherence_pct', 0.0):.1f}%",
            f"{cand.get('security_adherence_pct', 0.0):.1f}%",
            f"{comparison.security_adherence_delta:+.1f}%",
        )
    )
    print(
        fmt.format(
            "Overall Accuracy",
            f"{base.get('passed_cases', 0)}/{base.get('total_cases', 0)}",
            f"{cand.get('passed_cases', 0)}/{cand.get('total_cases', 0)}",
            f"{comparison.overall_accuracy_delta:+.1f}%",
        )
    )
    print(
        fmt.format(
            "Mean Latency (sec)",
            f"{base.get('mean_latency_sec', 0.0):.2f}s",
            f"{cand.get('mean_latency_sec', 0.0):.2f}s",
            f"{comparison.mean_latency_delta_sec:+.2f}s",
        )
    )
    print(
        fmt.format(
            "Median Latency (sec)",
            f"{comparison.median_latency_delta_sec:+.2f}s" if comparison.median_latency_delta_sec else "N/A",
            f"{cand.get('mean_latency_sec', 0.0):.2f}s",
            f"{comparison.speedup_pct:+.1f}% speedup",
        )
    )
    print("-" * 78)

    print(f"\n[*] Regressions Detected: {len(comparison.regressions)}")
    if comparison.regressions:
        for r in comparison.regressions:
            print(f"    [FAIL] Regression on Case ID: {r}")
    else:
        print("    [OK] Zero Regressions against verified baseline.")

    print("\n" + "=" * 78)
    if comparison.passed_promotion_gate:
        print("  PROMOTION GATE DECISION: PASSED [PROMOTE_CANDIDATE]")
        print("  Candidate satisfies all 100% accuracy, security, and zero-regression criteria.")
    else:
        print("  PROMOTION GATE DECISION: REJECTED [RETAIN_ROLLBACK_BASELINE]")
        print(f"  Recommendation: {comparison.recommendation}")
    print("=" * 78 + "\n")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Candidate Model against Verified Baseline")
    parser.add_argument(
        "--model",
        default="heretic-iris:latest",
        help="Ollama model tag to benchmark as candidate",
    )
    parser.add_argument(
        "--baseline",
        default="data/eval_reports/baseline_qwen2.5_7b.json",
        help="Path to baseline evaluation JSON",
    )
    parser.add_argument(
        "--candidate-output",
        default="data/eval_reports/candidate_heretic_iris.json",
        help="Path to write candidate evaluation report",
    )
    parser.add_argument(
        "--comparison-output",
        default="data/eval_reports/comparison_heretic_vs_baseline.json",
        help="Path to write comparative evaluation report",
    )
    parser.add_argument(
        "--endpoint",
        default="http://localhost:11434/v1",
        help="Ollama OpenAI-compatible API base URL",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip live evaluation and compare existing candidate-output against baseline",
    )

    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    candidate_output = Path(args.candidate_output)
    comparison_output = Path(args.comparison_output)

    print_banner(
        "IRIS MODEL CHECKPOINT COMPARISON & PROMOTION GATE",
        f"Evaluating '{args.model}' vs '{baseline_path.name}'",
    )

    # 1. Run or Load Candidate Evaluation
    comparator = ModelComparator(baseline_path=baseline_path)
    if args.skip_eval and candidate_output.exists():
        print(f"[*] Skipping live evaluation, loading existing report: {candidate_output}")
        candidate_report = comparator.load_report(candidate_output)
    else:
        candidate_report = await run_candidate_evaluation(
            model=args.model,
            endpoint=args.endpoint,
            candidate_output=candidate_output,
        )

    # 2. Run Comparative Analysis
    print("[*] Running comparative delta analysis and promotion gate evaluation...")
    comparison = comparator.compare(candidate=candidate_report)

    # 3. Persist Comparison Report
    comparator.save_comparison_report(comparison, comparison_output)
    print(f"[OK] Comparison report saved to: {comparison_output.resolve()}")

    # 4. Display Results
    display_comparison_summary(comparison)

    return 0 if comparison.passed_promotion_gate else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
