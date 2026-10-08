import pytest
import asyncio
from unittest.mock import AsyncMock
from src.observability.tracing import create_trace_context, TraceContext
from src.observability.event_bus import EventBus, EventLedger
from src.tools.manager import ToolManager
from src.tools.capability import Capability, PermissionLevel

@pytest.mark.asyncio
async def test_trace_context_hierarchy():
    trace = create_trace_context(device_id="pod-living-room", session_id="session-123", turn_id="turn-456")
    assert trace.device_id == "pod-living-room"
    assert trace.session_id == "session-123"
    assert trace.turn_id == "turn-456"
    assert bool(trace.request_id)
    assert bool(trace.trace_id)

@pytest.mark.asyncio
async def test_event_bus_pub_sub_and_ledger():
    bus = EventBus()
    received = []

    def on_event(evt):
        received.append(evt)

    bus.subscribe("telemetry.ping", on_event)
    trace = create_trace_context(device_id="pod-01")

    await bus.publish("telemetry.ping", {"status": "ok"}, trace=trace)

    assert len(received) == 1
    assert received[0].payload == {"status": "ok"}
    assert received[0].trace.device_id == "pod-01"

    # Verify ledger recorded the event
    ledger_events = bus.ledger.get_events("telemetry")
    assert len(ledger_events) == 1

@pytest.mark.asyncio
async def test_tool_manager_publishes_lifecycle_events():
    bus = EventBus()
    events = []

    bus.subscribe("*", lambda evt: events.append(evt.topic))

    class MockReg:
        def __init__(self):
            self.execute = AsyncMock(return_value={"status": "ok"})
        def get_schemas(self):
            return [{"name": "PingTool", "description": "Ping", "parameters": {}}]

    tm = ToolManager(registry=MockReg(), event_bus=bus)
    res = await tm.execute_tool("PingTool", {})

    assert res.status.value == "SUCCEEDED"
    assert "tool.execution.started" in events
    assert "tool.execution.succeeded" in events
