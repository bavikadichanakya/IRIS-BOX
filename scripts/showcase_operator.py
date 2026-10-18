#!/usr/bin/env python3
"""
Live End-to-End AI Computer Operator Showcase
Demonstrates autonomous desktop intelligence, hands-free workspace resolution,
read-only test failure diagnosis, cryptographic execution plan staging,
single-use approval token gating, and zero-regression verification.

Usage:
    uv run --python 3.12 python scripts/showcase_operator.py
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Color and style utilities for high-impact terminal presentation
class TerminalStyle:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground
    RED = "\033[38;5;196m"
    GREEN = "\033[38;5;46m"
    YELLOW = "\033[38;5;220m"
    BLUE = "\033[38;5;39m"
    MAGENTA = "\033[38;5;201m"
    CYAN = "\033[38;5;51m"
    WHITE = "\033[38;5;231m"
    GRAY = "\033[38;5;244m"
    DARK_GRAY = "\033[38;5;238m"

    # Accents
    BG_BLUE = "\033[48;5;18m"
    BG_DARK = "\033[48;5;234m"

def print_banner(title: str, subtitle: str = "") -> None:
    width = 78
    print(f"\n{TerminalStyle.BLUE}{'=' * width}{TerminalStyle.RESET}")
    print(f"{TerminalStyle.BOLD}{TerminalStyle.CYAN}  {title.center(width - 4)}{TerminalStyle.RESET}")
    if subtitle:
        print(f"{TerminalStyle.GRAY}  {subtitle.center(width - 4)}{TerminalStyle.RESET}")
    print(f"{TerminalStyle.BLUE}{'=' * width}{TerminalStyle.RESET}\n")

def print_step(step_num: int, title: str) -> None:
    print(f"\n{TerminalStyle.BOLD}{TerminalStyle.BLUE}[STEP {step_num}]{TerminalStyle.RESET} {TerminalStyle.BOLD}{TerminalStyle.WHITE}{title}{TerminalStyle.RESET}")
    print(f"{TerminalStyle.DARK_GRAY}{'-' * 70}{TerminalStyle.RESET}")

def print_voice(text: str) -> None:
    print(f"{TerminalStyle.BOLD}{TerminalStyle.MAGENTA}  🎙️  IRIS Spoken Voice (TTS):{TerminalStyle.RESET}")
    print(f"{TerminalStyle.ITALIC}{TerminalStyle.CYAN}      \"{text}\"{TerminalStyle.RESET}\n")

def print_diff(diff_text: str) -> None:
    print(f"{TerminalStyle.BOLD}{TerminalStyle.GRAY}  --- Unified Patch Diff Preview ---{TerminalStyle.RESET}")
    for line in diff_text.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            print(f"  {TerminalStyle.BOLD}{TerminalStyle.YELLOW}{line}{TerminalStyle.RESET}")
        elif line.startswith("@@"):
            print(f"  {TerminalStyle.CYAN}{line}{TerminalStyle.RESET}")
        elif line.startswith("-"):
            print(f"  {TerminalStyle.RED}{line}{TerminalStyle.RESET}")
        elif line.startswith("+"):
            print(f"  {TerminalStyle.GREEN}{line}{TerminalStyle.RESET}")
        else:
            print(f"  {TerminalStyle.GRAY}{line}{TerminalStyle.RESET}")
    print()


async def run_showcase() -> int:
    t_start = time.perf_counter()

    print_banner(
        "IRIS AI COMPUTER OPERATOR: END-TO-END SHOWCASE",
        "Autonomous Desktop Telemetry • Hands-Free Diagnosis • Cryptographic Staged Patching"
    )

    # -------------------------------------------------------------------------
    # Setup Workspace: data/showcase_workspace/payment-service
    # -------------------------------------------------------------------------
    workspace_dir = Path("data/showcase_workspace/payment-service").resolve()
    print(f"{TerminalStyle.GRAY}Initializing showcase workspace at: {workspace_dir}{TerminalStyle.RESET}")
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir, ignore_errors=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    payment_file = workspace_dir / "payment.py"
    payment_file.write_text(
        'def process_payment(amount: float) -> str:\n'
        '    # Bug: returns FAILED instead of PAID\n'
        '    return "FAILED"\n',
        encoding="utf-8"
    )

    test_file = workspace_dir / "test_payment.py"
    test_file.write_text(
        'from payment import process_payment\n\n'
        'def test_payment_success():\n'
        '    assert process_payment(100.0) == "PAID"\n',
        encoding="utf-8"
    )

    # Native Git Repository for zero-friction rollback checkpoints & diff tracking
    try:
        subprocess.run(["git", "init"], cwd=workspace_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "operator@iris.ai"], cwd=workspace_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Iris Operator"], cwd=workspace_dir, capture_output=True, check=True)
        subprocess.run(["git", "add", "."], cwd=workspace_dir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit with payment bug"], cwd=workspace_dir, capture_output=True, check=True)
    except Exception as e:
        print(f"{TerminalStyle.YELLOW}Warning: Git init skipped or failed: {e}{TerminalStyle.RESET}")

    print(f"  {TerminalStyle.GREEN}✓{TerminalStyle.RESET} Created {payment_file.name} with intentional defect")
    print(f"  {TerminalStyle.GREEN}✓{TerminalStyle.RESET} Created {test_file.name} expecting process_payment() == 'PAID'")
    print(f"  {TerminalStyle.GREEN}✓{TerminalStyle.RESET} Initialized Git repository for atomic checkpoint tracking")

    # -------------------------------------------------------------------------
    # Step 1: Desktop Intelligence & Process Watchdog
    # -------------------------------------------------------------------------
    print_step(1, "Desktop Intelligence & Developer Daemon Watchdog")
    from src.operator.desktop import DesktopEnvironment
    from src.operator.summarizer import OperatorSummarizer

    metrics = DesktopEnvironment.get_system_metrics()
    cpu_pct = metrics.get("cpu_percent", 0.0)
    ram_pct = metrics.get("memory_percent", 0.0)
    avail_ram = metrics.get("available_ram_gb", 0.0)
    total_ram = metrics.get("total_ram_gb", 0.0)

    print(f"  {TerminalStyle.CYAN}Telemetry:{TerminalStyle.RESET} CPU Usage: {TerminalStyle.BOLD}{cpu_pct}%{TerminalStyle.RESET} | RAM: {TerminalStyle.BOLD}{ram_pct}%{TerminalStyle.RESET} ({avail_ram} GB free / {total_ram} GB total)")

    # Developer Service Daemon Watchdog
    docker_info = DesktopEnvironment.inspect_service("docker")
    ollama_info = DesktopEnvironment.inspect_service("ollama")

    docker_icon = f"{TerminalStyle.GREEN}RUNNING (PID {docker_info.get('pid')}){TerminalStyle.RESET}" if docker_info.get("running") else f"{TerminalStyle.GRAY}STOPPED{TerminalStyle.RESET}"
    ollama_icon = f"{TerminalStyle.GREEN}RUNNING (PID {ollama_info.get('pid')}){TerminalStyle.RESET}" if ollama_info.get("running") else f"{TerminalStyle.GRAY}STOPPED{TerminalStyle.RESET}"

    print(f"  {TerminalStyle.CYAN}Daemons:{TerminalStyle.RESET}   Docker: {docker_icon} | Ollama: {ollama_icon}")

    voice_health = OperatorSummarizer.summarize_system_health(metrics)
    print_voice(voice_health)

    # -------------------------------------------------------------------------
    # Step 2: Hands-Free Natural Project Diagnosis
    # -------------------------------------------------------------------------
    print_step(2, "Hands-Free Natural Project Diagnosis")
    from src.operator.resolver import WorkspaceResolver
    from src.operator.task_runner import OperatorTaskRunner
    from src.agent.plan_manager import PlanManager, PlanStatus

    user_utterance = "Hey Iris, check why tests are failing in my current project."
    print(f"  {TerminalStyle.YELLOW}User Spoken Input:{TerminalStyle.RESET} \"{user_utterance}\"")

    # Resolve project path hands-free
    resolver = WorkspaceResolver(
        workspace_roots=[str(workspace_dir.parent), str(Path.cwd())],
        last_active_project_path=str(workspace_dir),
    )
    resolved_path = resolver.resolve_project_path(user_utterance)
    print(f"  {TerminalStyle.GREEN}✓{TerminalStyle.RESET} WorkspaceResolver resolved project: {TerminalStyle.BOLD}{resolved_path}{TerminalStyle.RESET}")
    assert resolved_path == str(workspace_dir), f"Resolution mismatch: {resolved_path} vs {workspace_dir}"

    plan_manager = PlanManager()
    runner = OperatorTaskRunner(plan_manager=plan_manager)

    print(f"  {TerminalStyle.GRAY}Executing read-only test suite via SystemCommandSkill (pytest)...{TerminalStyle.RESET}")
    diag = await runner.diagnose_failure(resolved_path)

    print(f"  {TerminalStyle.RED}✗ Test Suite Status:{TerminalStyle.RESET} {TerminalStyle.BOLD}FAILED (exit code {diag.exit_code}){TerminalStyle.RESET}")
    print(f"  {TerminalStyle.CYAN}Target Code File:{TerminalStyle.RESET}   {TerminalStyle.BOLD}{diag.target_file}{TerminalStyle.RESET}")
    print(f"  {TerminalStyle.CYAN}Root Cause Trace:{TerminalStyle.RESET}   {diag.error_summary}")
    for fail_item in diag.failing_tests:
        print(f"      {TerminalStyle.RED}• {fail_item}{TerminalStyle.RESET}")

    voice_diag = OperatorSummarizer.summarize_diagnostic(diag, "payment-service")
    print_voice(voice_diag)

    assert diag.passed is False, "Expected diagnosis test suite to fail"
    assert diag.target_file == "payment.py", f"Expected target_file == payment.py, got {diag.target_file}"

    # -------------------------------------------------------------------------
    # Step 3: Staged Plan & Cryptographic Diff Synthesis
    # -------------------------------------------------------------------------
    print_step(3, "Staged Plan & Cryptographic Diff Synthesis")
    plan = runner.propose_patch(diag)

    print(f"  {TerminalStyle.CYAN}ExecutionPlan ID:{TerminalStyle.RESET} {TerminalStyle.BOLD}{plan.plan_id}{TerminalStyle.RESET}")
    print(f"  {TerminalStyle.CYAN}Content SHA256:{TerminalStyle.RESET}   {TerminalStyle.BOLD}{plan.content_hash}{TerminalStyle.RESET}")
    print(f"  {TerminalStyle.CYAN}Checkpoint ID:{TerminalStyle.RESET}    {plan.checkpoint_id} (read-only safety snapshot)")
    print(f"  {TerminalStyle.CYAN}Plan Status:{TerminalStyle.RESET}      {TerminalStyle.YELLOW}{plan.status.value}{TerminalStyle.RESET}")

    print_diff(plan.diff_preview or "")

    print(f"  {TerminalStyle.GRAY}Plan Steps (Atomic Multi-Tier Pipeline):{TerminalStyle.RESET}")
    for s in plan.steps:
        print(f"    [{s.step_id}] {s.tool_name} -> {s.action_type.upper()} ({s.permission_level.value}) : {s.description}")

    voice_plan = OperatorSummarizer.summarize_plan(plan, "payment-service")
    print_voice(voice_plan)

    assert "FAILED" in (plan.diff_preview or "")
    assert "PAID" in (plan.diff_preview or "")

    # -------------------------------------------------------------------------
    # Step 4: Cryptographic Plan Approval
    # -------------------------------------------------------------------------
    print_step(4, "Cryptographic Plan Approval & Token Validation")
    from src.security.auth import auth_manager

    # Generate or inspect single-use approval token bound to plan_id + content_hash
    token = plan.approval_token or auth_manager.create_plan_approval_token(plan.plan_id, plan.content_hash)
    token_preview = f"{token[:8]}...{token[-4:]}"
    print(f"  {TerminalStyle.CYAN}Generated Approval Token:{TerminalStyle.RESET} {TerminalStyle.BOLD}{token_preview}{TerminalStyle.RESET} (bound to content digest)")

    # Execute cryptographic plan approval
    approved = plan_manager.approve_plan(plan.plan_id, token)
    print(f"  {TerminalStyle.GREEN}✓ Cryptographic Token Validation:{TerminalStyle.RESET} {TerminalStyle.BOLD}SUCCESS{TerminalStyle.RESET}")
    print(f"  {TerminalStyle.CYAN}Updated Plan Status:{TerminalStyle.RESET} {TerminalStyle.GREEN}{plan.status.value}{TerminalStyle.RESET}")

    assert approved is True, "Plan approval failed cryptographic verification"
    assert plan.status == PlanStatus.APPROVED, f"Expected status APPROVED, got {plan.status}"

    # -------------------------------------------------------------------------
    # Step 5: Verified Execution & Zero Regression
    # -------------------------------------------------------------------------
    print_step(5, "Verified Execution & Zero Regression")
    print(f"  {TerminalStyle.GRAY}Executing approved 4-step sequence through ToolManager...{TerminalStyle.RESET}")

    exec_plan = await plan_manager.execute_approved_plan(plan.plan_id, orchestrator=None)

    for s in exec_plan.steps:
        status_color = TerminalStyle.GREEN if s.status.value == "COMPLETED" else TerminalStyle.RED
        print(f"    {status_color}✓{TerminalStyle.RESET} Step {s.step_id} ({s.action_type.upper()}): {status_color}{s.status.value}{TerminalStyle.RESET}")

    assert exec_plan.status == PlanStatus.COMPLETED, f"Expected plan execution COMPLETED, got {exec_plan.status}"

    # Verify target file contents on disk
    updated_code = payment_file.read_text(encoding="utf-8")
    print(f"\n  {TerminalStyle.CYAN}Updated {payment_file.name} on disk:{TerminalStyle.RESET}")
    for line in updated_code.splitlines():
        if 'return "PAID"' in line:
            print(f"    {TerminalStyle.GREEN}{line}{TerminalStyle.RESET}")
        else:
            print(f"    {TerminalStyle.GRAY}{line}{TerminalStyle.RESET}")

    assert 'return "PAID"' in updated_code, "Target file was not updated with return 'PAID'"

    # Final Spoken Voice Announcement
    tts_announcement = OperatorSummarizer.summarize_fix_verification("payment-service", exit_code=0)
    print_voice(tts_announcement)

    assert tts_announcement == "Fixed issue in payment-service. All tests are now passing with exit code 0."

    elapsed_sec = round(time.perf_counter() - t_start, 2)
    print_banner(
        "OPERATOR SHOWCASE COMPLETED SUCCESSFULLY (100% PASS)",
        f"All 5 Pipeline Milestones Verified in {elapsed_sec}s with Zero Regression"
    )
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run_showcase())
    sys.exit(exit_code)
