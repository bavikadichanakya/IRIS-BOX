"""
Standard Evaluation Datasets and Benchmark Suites for IRIS.
Covers 6 core tool domains:
1. Smart Home Automation (HomeAssistantTool)
2. System Terminal Execution & Planning (SystemCommandTool)
3. Web Navigation & Playwright (BrowserActionTool)
4. AI Project Operator & Workspace Rollback (ProjectOperatorTool)
5. Desktop Environment & Process Intelligence (DesktopIntelligenceTool)
6. Window Focus & Multi-App Automation (WindowAutomationTool)
"""

from typing import List
from src.eval.models import TaskBenchmarkCase
from src.tools.capability import PermissionLevel


def get_standard_benchmark_suite() -> List[TaskBenchmarkCase]:
    """Return the canonical 6-tool-domain benchmark test suite."""
    return [
        TaskBenchmarkCase(
            id="smart_home_lights",
            case_id="smart_home_lights",
            user_prompt="Turn off the living room lights",
            expected_intent="smart_home",
            expected_tool="HomeAssistantTool",
            expected_permission=PermissionLevel.PROTECTED,
            expected_params_subset={"action": "off", "domain": "light"},
            ground_truth_tokens=["light", "off"],
        ),
        TaskBenchmarkCase(
            id="system_terminal_echo",
            case_id="system_terminal_echo",
            user_prompt="Create an execution plan to echo hello and dir",
            expected_intent="system_command",
            expected_tool="SystemCommandTool",
            expected_permission=PermissionLevel.SENSITIVE,
            expected_params_subset={"command": "echo hello"},
            ground_truth_tokens=["hello"],
        ),
        TaskBenchmarkCase(
            id="browser_navigation",
            case_id="browser_navigation",
            user_prompt="Open https://github.com in the browser",
            expected_intent="browser",
            expected_tool="BrowserActionTool",
            expected_permission=PermissionLevel.PUBLIC,
            expected_params_subset={"action": "navigate"},
            ground_truth_tokens=["github.com"],
        ),
        TaskBenchmarkCase(
            id="operator_workspace_diagnosis",
            case_id="operator_workspace_diagnosis",
            user_prompt="Check why tests are failing in my current project",
            expected_intent="project_operator",
            expected_tool="ProjectOperatorTool",
            expected_permission=PermissionLevel.SENSITIVE,
            expected_params_subset={"action": "diagnose"},
            ground_truth_tokens=["diagnose"],
        ),
        TaskBenchmarkCase(
            id="desktop_telemetry_top_ram",
            case_id="desktop_telemetry_top_ram",
            user_prompt="Check what process is consuming the most memory right now",
            expected_intent="desktop_intelligence",
            expected_tool="DesktopIntelligenceTool",
            expected_permission=PermissionLevel.PROTECTED,
            expected_params_subset={"action": "get_top_processes", "sort_by": "memory"},
            ground_truth_tokens=["memory"],
        ),
        TaskBenchmarkCase(
            id="window_focus_browser",
            case_id="window_focus_browser",
            user_prompt="Switch to my browser window and bring it to the front",
            expected_intent="window_automation",
            expected_tool="WindowAutomationTool",
            expected_permission=PermissionLevel.PROTECTED,
            expected_params_subset={"action": "focus_window", "query": "browser"},
            ground_truth_tokens=["browser"],
        ),
    ]


BENCHMARK_CASES_6_DOMAINS = get_standard_benchmark_suite()
