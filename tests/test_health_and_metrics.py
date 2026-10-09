import pytest
from unittest.mock import MagicMock, AsyncMock

from src.observability.event_bus import EventBus
from src.observability.metrics import RuntimeMetrics
from src.observability.health import HealthSupervisor, HealthState, SubsystemHealth


@pytest.mark.asyncio
async def test_runtime_metrics_event_bus_accumulation():
    bus = EventBus()
    metrics = RuntimeMetrics(event_bus=bus)

    # 1. Publish tool events
    await bus.publish("tool.invoked", {"tool_name": "HomeAssistantTool", "request_id": "r1"})
    await bus.publish("tool.completed", {"tool_name": "HomeAssistantTool", "duration_ms": 50.0, "output": {"ok": True}})
    await bus.publish("tool.invoked", {"tool_name": "SystemCommandTool", "request_id": "r2"})
    await bus.publish("tool.denied", {"tool_name": "SystemCommandTool", "duration_ms": 5.0, "error": "CONFIRMATION_REQUIRED"})

    # 2. Publish voice events
    await bus.publish("voice.barge_in", {"device_id": "pod-1"})
    await bus.publish("voice.stt.completed", {"duration_ms": 120.0})

    # 3. Publish request & fleet events
    await bus.publish("request.invoked", {})
    await bus.publish("request.completed", {})
    await bus.publish("fleet.device.connected", {})

    snapshot = metrics.get_metrics_snapshot()

    assert snapshot["requests"]["total"] == 1
    assert snapshot["requests"]["successful"] == 1
    assert snapshot["tools"]["total_invocations"] == 2
    assert snapshot["tools"]["invocations_by_tool"]["HomeAssistantTool"] == 1
    assert snapshot["tools"]["invocations_by_tool"]["SystemCommandTool"] == 1
    assert snapshot["tools"]["denial_rate"] == 0.5
    assert snapshot["voice"]["barge_in_count"] == 1
    assert snapshot["fleet"]["connected_devices"] == 1


@pytest.mark.asyncio
async def test_health_supervisor_liveness_vs_readiness():
    supervisor = HealthSupervisor()

    # 1. Liveness check should return HEALTHY lightweight report
    live_report = await supervisor.get_health_status(check_readiness=False)
    assert live_report.status == HealthState.HEALTHY
    assert "api" in live_report.subsystems
    assert len(live_report.subsystems) == 1

    # 2. Readiness check evaluates all subsystems
    ready_report = await supervisor.get_health_status(check_readiness=True)
    assert ready_report.status in (HealthState.HEALTHY, HealthState.DEGRADED, HealthState.UNHEALTHY)
    assert len(ready_report.subsystems) >= 5
    assert "tools" in ready_report.subsystems
    assert "voice" in ready_report.subsystems


@pytest.mark.asyncio
async def test_health_supervisor_degraded_unhealthy_reporting():
    supervisor = HealthSupervisor()

    # Manually override storage subsystem to UNHEALTHY
    supervisor.set_subsystem_status(
        "storage",
        HealthState.UNHEALTHY,
        message="Database disk read error"
    )

    report = await supervisor.get_health_status(check_readiness=True)
    assert report.status == HealthState.UNHEALTHY
    assert report.subsystems["storage"].status == HealthState.UNHEALTHY
    assert "Database disk read error" in report.subsystems["storage"].message
    assert "Subsystems requiring attention" in report.diagnostics
