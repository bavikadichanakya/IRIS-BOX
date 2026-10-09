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
