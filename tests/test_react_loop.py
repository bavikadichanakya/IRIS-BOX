import pytest
from unittest.mock import AsyncMock
from src.agent.react_loop import ReActLoop
from src.tools.manager import ToolManager
from src.observability.tracing import create_trace_context

@pytest.mark.asyncio
async def test_react_loop_step_execution():
    class MockReg:
        def __init__(self):
            self.execute = AsyncMock(return_value={"temperature": 22})
        def get_schemas(self):
            return [{"name": "WeatherTool", "description": "Get weather", "parameters": {}}]

    tm = ToolManager(registry=MockReg())
    loop = ReActLoop(tool_manager=tm, max_iterations=3)

    trace = create_trace_context("device-01")
    result = await loop.execute_step("WeatherTool", {"location": "Living Room"}, trace_context=trace)

    assert result.status.value == "SUCCEEDED"
    assert result.output == {"temperature": 22}

    feedback = loop.format_tool_feedback("WeatherTool", result)
    assert feedback["tool"] == "WeatherTool"
    assert feedback["status"] == "SUCCEEDED"
    assert feedback["output"] == {"temperature": 22}

@pytest.mark.asyncio
async def test_react_loop_protected_tool_policy():
    class MockHomeReg:
        def __init__(self):
            self.execute = AsyncMock(return_value={"status": "turned_on"})
        def get_schemas(self):
            return [{"name": "HomeAssistantTool", "description": "Control smart home", "parameters": {}}]

    tm = ToolManager(registry=MockHomeReg())
    loop = ReActLoop(tool_manager=tm)

    # 1. Denied when device_id is unverified/unknown
    trace_unknown = create_trace_context(device_id="unknown")
    res_denied = await loop.execute_step("HomeAssistantTool", {"action": "turn_on"}, trace_context=trace_unknown)
    assert res_denied.status.value == "DENIED"
    assert "requires a verified device_id" in res_denied.error

    # 2. Allowed when device_id is provided in trace
    trace = create_trace_context(device_id="device-living-room")
    res_allowed = await loop.execute_step("HomeAssistantTool", {"action": "turn_on"}, trace_context=trace)
    assert res_allowed.status.value == "SUCCEEDED"
    assert res_allowed.output == {"status": "turned_on"}

@pytest.mark.asyncio
async def test_react_loop_sensitive_tool_policy():
    class MockSystemReg:
        def __init__(self):
            self.execute = AsyncMock(return_value={"output": "ok"})
        def get_schemas(self):
            return [{"name": "SystemCommandTool", "description": "Run shell command", "parameters": {}}]

    tm = ToolManager(registry=MockSystemReg())
    loop = ReActLoop(tool_manager=tm)

    # 1. Denied when confirmed=False (default)
    res_denied = await loop.execute_step("SystemCommandTool", {"command": "ls"})
    assert res_denied.status.value == "DENIED"
    assert "CONFIRMATION_REQUIRED" in res_denied.error

    # 2. Allowed when confirmed=True in context
    res_confirmed = await loop.execute_step("SystemCommandTool", {"command": "ls"}, context={"confirmed": True})
    assert res_confirmed.status.value == "SUCCEEDED"
    assert res_confirmed.output == {"output": "ok"}

