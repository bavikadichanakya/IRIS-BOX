import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.tools.capability import Capability, ExecutionStatus, PermissionLevel
from src.tools.permissions import PermissionManager
from src.tools.manager import ToolManager

class MockRegistry:
    def __init__(self):
        self.execute = AsyncMock()
    def get_schemas(self):
        return [
            {
                "name": "EchoTool",
                "description": "Echoes text",
                "parameters": {"type": "object", "properties": {"msg": {"type": "string"}}}
            }
        ]

@pytest.mark.asyncio
async def test_tool_manager_success():
    registry = MockRegistry()
    registry.execute.return_value = {"result": "hello world"}
    tm = ToolManager(registry=registry)

    res = await tm.execute_tool(
        name="EchoTool",
        arguments={"msg": "hello"},
        request_id="req-1",
        trace_id="tr-1",
        context={"device_id": "test-dev"}
    )
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.output == {"result": "hello world"}
    assert res.tool_name == "EchoTool"
    assert res.request_id == "req-1"

@pytest.mark.asyncio
async def test_tool_manager_denied():
    registry = MockRegistry()
    tm = ToolManager(registry=registry)
    # Register sensitive capability requiring confirmation
    tm.register_capability(Capability(
        name="EchoTool",
        description="Echoes text",
        permission_level=PermissionLevel.SENSITIVE,
        requires_confirmation=True
    ))

    res = await tm.execute_tool(
        name="EchoTool",
        arguments={"msg": "hello"},
        context={"confirmed": False}
    )
    assert res.status == ExecutionStatus.DENIED
    assert "CONFIRMATION_REQUIRED" in res.error

@pytest.mark.asyncio
async def test_tool_manager_timeout():
    registry = MockRegistry()
    async def slow_exec(*args, **kwargs):
        await asyncio.sleep(0.5)
        return "done"
    registry.execute.side_effect = slow_exec
    tm = ToolManager(registry=registry)
    tm.register_capability(Capability(
        name="EchoTool",
        description="Echoes text",
        execution_timeout_sec=0.1
    ))

    res = await tm.execute_tool(name="EchoTool", arguments={})
    assert res.status == ExecutionStatus.TIMEOUT
    assert "timed out" in res.error

@pytest.mark.asyncio
async def test_tool_manager_unavailable():
    registry = MockRegistry()
    tm = ToolManager(registry=registry)

    res = await tm.execute_tool(name="NonExistentTool", arguments={})
    assert res.status == ExecutionStatus.UNAVAILABLE

@pytest.mark.asyncio
async def test_tool_manager_audit_telemetry():
    from src.observability.event_bus import EventBus
    bus = EventBus()
    events = []
    bus.subscribe("*", lambda evt: events.append(evt))

    registry = MockRegistry()
    registry.execute.return_value = {"res": "ok"}
    tm = ToolManager(registry=registry, event_bus=bus)

    res = await tm.execute_tool(
        name="EchoTool",
        arguments={"msg": "test"},
        request_id="req-99",
        trace_id="tr-99",
        context={"device_id": "pod-101"}
    )
    assert res.status == ExecutionStatus.SUCCEEDED

    topics = [e.topic for e in events]
    assert "tool.invoked" in topics
    assert "tool.completed" in topics

    invoked_evt = next(e for e in events if e.topic == "tool.invoked")
    assert invoked_evt.payload["tool_name"] == "EchoTool"
    assert invoked_evt.payload["request_id"] == "req-99"
    assert invoked_evt.payload["context"]["device_id"] == "pod-101"

    completed_evt = next(e for e in events if e.topic == "tool.completed")
    assert completed_evt.payload["status"] == "SUCCEEDED"
    assert completed_evt.payload["output"] == {"res": "ok"}

@pytest.mark.asyncio
async def test_tool_manager_register_capability_runtime():
    registry = MockRegistry()
    tm = ToolManager(registry=registry)

    cap = Capability(
        name="DynamicTool",
        description="Runtime registered capability",
        permission_level=PermissionLevel.PUBLIC
    )
    tm.register_capability(cap)

    fetched = tm.get_capability("DynamicTool")
    assert fetched is not None
    assert fetched.name == "DynamicTool"
    assert fetched.permission_level == PermissionLevel.PUBLIC

