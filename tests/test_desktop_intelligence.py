from __future__ import annotations
import os
import psutil
import pytest
from starlette.testclient import TestClient

from src.models.schemas import DesktopAction
from src.operator.desktop import DesktopEnvironment
from src.operator.summarizer import OperatorSummarizer
from src.security import auth_manager
from src.server.app import app
from src.skills.core.desktop_skill import DesktopIntelligenceSkill
from src.skills.registry import SkillRegistry
from src.tools.capability import PermissionLevel
from src.tools.registry import ToolRegistry, DesktopIntelligenceTool


def test_system_metrics_extraction():
    """Verify system telemetry extracts non-null CPU %, RAM %, disk %, and battery state."""
    metrics = DesktopEnvironment.get_system_metrics()
    assert isinstance(metrics, dict)

    # 1. CPU Telemetry
    assert "cpu_percent" in metrics
    assert isinstance(metrics["cpu_percent"], (int, float))
    assert 0.0 <= metrics["cpu_percent"] <= 100.0

    # 2. RAM Telemetry
    assert "memory_percent" in metrics
    assert isinstance(metrics["memory_percent"], (int, float))
    assert 0.0 <= metrics["memory_percent"] <= 100.0
    assert metrics["total_ram_gb"] > 0.0
    assert metrics["available_ram_gb"] >= 0.0
    assert metrics["used_ram_gb"] >= 0.0

    # 3. Disk Telemetry
    assert "disk_total_gb" in metrics
    assert "disk_percent" in metrics
    assert metrics["disk_total_gb"] > 0.0
    assert 0.0 <= metrics["disk_percent"] <= 100.0

    # 4. Battery State
    assert "power_plugged" in metrics
    assert "battery_percent" in metrics


def test_process_sorting_cpu_and_memory():
    """Verify process inspector retrieves top processes sorted by CPU and memory usage."""
    # 1. Sort by CPU
    top_cpu = DesktopEnvironment.get_top_processes(limit=5, sort_by="cpu")
    assert isinstance(top_cpu, list)
    assert len(top_cpu) <= 5
    if len(top_cpu) >= 2:
        for i in range(len(top_cpu) - 1):
            assert top_cpu[i]["cpu_percent"] >= top_cpu[i + 1]["cpu_percent"]

    first_cpu = top_cpu[0]
    assert "pid" in first_cpu
    assert "name" in first_cpu
    assert "cpu_percent" in first_cpu
    assert "memory_mb" in first_cpu

    # 2. Sort by Memory
    top_mem = DesktopEnvironment.get_top_processes(limit=5, sort_by="memory")
    assert isinstance(top_mem, list)
    assert len(top_mem) <= 5
    if len(top_mem) >= 2:
        for i in range(len(top_mem) - 1):
            assert top_mem[i]["memory_mb"] >= top_mem[i + 1]["memory_mb"]

    first_mem = top_mem[0]
    assert first_mem["memory_mb"] > 0


def test_blacklist_guard_protects_critical_processes():
    """Verify kill_process strictly blocks PID 0, PID 4, self PID, and protected system binaries."""
    # 1. PID 0 (System Idle)
    with pytest.raises(PermissionError) as exc_0:
        DesktopEnvironment.kill_process(0)
    assert "SECURITY_DENIED" in str(exc_0.value)

    # 2. PID 4 (System)
    with pytest.raises(PermissionError) as exc_4:
        DesktopEnvironment.kill_process(4)
    assert "SECURITY_DENIED" in str(exc_4.value)

    # 3. Current Process (Assistant Self-Termination Guard)
    with pytest.raises(PermissionError) as exc_self:
        DesktopEnvironment.kill_process(os.getpid())
    assert "SECURITY_DENIED" in str(exc_self.value)

    # 4. Protected System Binary (e.g., explorer.exe)
    explorer_pid = None
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and "explorer" in proc.info["name"].lower():
                explorer_pid = proc.info["pid"]
                break
        except Exception:
            pass

    if explorer_pid:
        with pytest.raises(PermissionError) as exc_exp:
            DesktopEnvironment.kill_process(explorer_pid)
        assert "SECURITY_DENIED" in str(exc_exp.value)

    # 5. Non-existent PID
    with pytest.raises(ProcessLookupError):
        DesktopEnvironment.kill_process(999999999)


def test_window_inspection_without_crashing():
    """Verify window enumeration retrieves open desktop windows safely."""
    windows = DesktopEnvironment.get_visible_windows()
    assert isinstance(windows, list)
    # If running on Windows, verify format of retrieved items
    if os.name == "nt" and len(windows) > 0:
        win = windows[0]
        assert "hwnd" in win
        assert "title" in win
        assert "pid" in win
        assert "process_name" in win
        assert len(win["title"]) > 0


def test_service_watchdog_inspection():
    """Verify developer service inspection for active and stopped daemons."""
    # 1. Unknown / stopped fake daemon
    stopped_info = DesktopEnvironment.inspect_service("non_existent_iris_mock_service")
    assert stopped_info["running"] is False
    assert stopped_info["status"] == "stopped"
    assert stopped_info["pid"] is None

    # 2. Inspect common services dictionary
    common = DesktopEnvironment.inspect_common_services()
    assert isinstance(common, dict)
    assert "docker" in common
    assert "ollama" in common
    assert "wsl" in common
    assert isinstance(common["ollama"]["running"], bool)


def test_natural_voice_summaries():
    """Verify concise voice output formatting for TTS pipelines."""
    # 1. System Health Summary
    sample_metrics = {
        "cpu_percent": 14.2,
        "memory_percent": 62.0,
        "available_ram_gb": 6.1,
        "battery_percent": 85,
        "power_plugged": False,
    }
    summary = OperatorSummarizer.summarize_system_health(sample_metrics)
    assert "CPU is at 14%" in summary
    assert "RAM is at 62%" in summary
    assert "6.1 GB available" in summary
    assert "Running on battery at 85%" in summary
    assert len(summary) < 120  # Concise voice response

    # 2. Top Consumers Summary
    sample_procs = [
        {"name": "chrome.exe", "memory_mb": 1433.6, "cpu_percent": 2.1},
        {"name": "pycharm64.exe", "memory_mb": 980.0, "cpu_percent": 1.4},
    ]
    mem_summary = OperatorSummarizer.summarize_top_consumers(sample_procs, resource_type="memory")
    assert "top memory consumer is Chrome using 1.4 GB" in mem_summary
    assert "Pycharm64 at 980 MB" in mem_summary

    cpu_procs = [
        {"name": "python.exe", "memory_mb": 120.0, "cpu_percent": 18.5},
        {"name": "node.exe", "memory_mb": 85.0, "cpu_percent": 12.1},
    ]
    cpu_summary = OperatorSummarizer.summarize_top_consumers(cpu_procs, resource_type="cpu")
    assert "top cpu consumer is Python using 18.5%" in cpu_summary
    assert "Node at 12.1%" in cpu_summary

    # 3. Service Status Summary
    running_svc = OperatorSummarizer.summarize_service_status("docker", True, {"pid": 8420})
    assert running_svc == "Docker is currently running on PID 8420."

    stopped_svc = OperatorSummarizer.summarize_service_status("ollama", False)
    assert stopped_svc == "Ollama daemon is not running."


@pytest.mark.asyncio
async def test_desktop_intelligence_skill_execution():
    """Verify DesktopIntelligenceSkill manifests, actions, and permission elevation."""
    skill = DesktopIntelligenceSkill()
    assert skill.manifest.name == "desktop_intelligence"
    assert skill.manifest.permission_level == PermissionLevel.PROTECTED

    # 1. Health check
    health = await skill.check_health()
    assert health.healthy is True

    # 2. System Metrics Action
    res_metrics = await skill.execute({"action": "get_system_metrics"})
    assert res_metrics.success is True
    assert "metrics" in res_metrics.output
    assert "voice_summary" in res_metrics.output

    # 3. Top Processes Action
    res_procs = await skill.execute({"action": "get_top_processes", "sort_by": "memory", "limit": 3})
    assert res_procs.success is True
    assert len(res_procs.output["processes"]) <= 3

    # 4. Service Watchdog Action
    res_svc = await skill.execute({"action": "check_service", "service_name": "ollama"})
    assert res_svc.success is True
    assert "service" in res_svc.output

    # 5. Visible Windows Action
    res_win = await skill.execute({"action": "get_visible_windows"})
    assert res_win.success is True
    assert "windows" in res_win.output

    # 6. Kill Process without Confirmation (Permission Tier Elevation to SENSITIVE)
    res_kill_unconf = await skill.execute({"action": "kill_process", "pid": 12345}, context={})
    assert res_kill_unconf.success is False
    assert "CONFIRMATION_REQUIRED" in res_kill_unconf.error
    assert res_kill_unconf.metadata.get("requires_confirmation") is True

    # 7. Kill Process targeting Blacklisted System PID with Confirmation
    res_kill_blocked = await skill.execute(
        {"action": "kill_process", "pid": 4},
        context={"confirmed": True},
    )
    assert res_kill_blocked.success is False
    assert "SECURITY_DENIED" in res_kill_blocked.error


def test_desktop_intelligence_tool_registry():
    """Verify tool registration and execution through ToolRegistry."""
    tool = ToolRegistry.get_tool("DesktopIntelligenceTool")
    assert isinstance(tool, DesktopIntelligenceTool)

    # 1. Execute metrics action
    exec_res = tool.execute(DesktopAction(action="get_system_metrics"))
    assert exec_res.success is True
    assert exec_res.output_payload["status"] == "TELEMETRY_SUCCESS"
    assert "voice_confirmation" in exec_res.output_payload

    # 2. Execute process inspection
    proc_res = tool.execute(DesktopAction(action="get_top_processes", sort_by="cpu", limit=2))
    assert proc_res.success is True
    assert proc_res.output_payload["status"] == "PROCESSES_RETRIEVED"
    assert len(proc_res.output_payload["processes"]) <= 2

    # 3. Execute kill on protected process PID 4 -> blocked
    kill_res = tool.execute(DesktopAction(action="kill_process", pid=4))
    assert kill_res.success is False
    assert "SECURITY_DENIED" in kill_res.error


def test_desktop_rest_endpoints_and_security():
    """Verify /api/desktop REST endpoints authentication, schemas, and security denial."""
    api_key = auth_manager.get_master_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    with TestClient(app) as client:
        # 1. Unauthenticated request -> 401 Unauthorized
        unauth_res = client.get("/api/desktop/metrics")
        assert unauth_res.status_code == 401

        # 2. System Metrics Endpoint
        metrics_res = client.get("/api/desktop/metrics", headers=headers)
        assert metrics_res.status_code == 200
        metrics_data = metrics_res.json()
        assert "cpu_percent" in metrics_data
        assert "memory_percent" in metrics_data
        assert "total_ram_gb" in metrics_data

        # 3. Processes Endpoint
        proc_res = client.get("/api/desktop/processes?sort_by=memory&limit=3", headers=headers)
        assert proc_res.status_code == 200
        proc_data = proc_res.json()
        assert proc_data["sort_by"] == "memory"
        assert len(proc_data["processes"]) <= 3

        # 4. Services Endpoint
        svc_res = client.get("/api/desktop/services", headers=headers)
        assert svc_res.status_code == 200
        svc_data = svc_res.json()
        assert "docker" in svc_data
        assert "ollama" in svc_data

        # 5. Windows Endpoint
        win_res = client.get("/api/desktop/windows", headers=headers)
        assert win_res.status_code == 200
        win_data = win_res.json()
        assert "count" in win_data
        assert "windows" in win_data

        # 6. Kill Process Endpoint - Security Denial for Protected System PID (PID 4)
        kill_res = client.post("/api/desktop/kill", json={"pid": 4}, headers=headers)
        assert kill_res.status_code == 403
        assert "SECURITY_DENIED" in kill_res.json()["detail"]
