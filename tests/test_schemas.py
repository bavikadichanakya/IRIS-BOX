import pytest
from pydantic import ValidationError

from src.models.schemas import (
    AgentExecutionResult,
    BrowserAction,
    LaptopSystemAction,
    SmartHomeAction,
    VoiceCommandPayload,
)


def test_smart_home_action_serialization():
    """
    Test SmartHomeAction can be serialized correctly.
    """
    action_data = {
        "entity_id": "light.living_room",
        "domain": "light",
        "action": "on",
        "attributes": {"brightness": 255},
    }
    action = SmartHomeAction(**action_data)
    assert action.model_dump() == action_data

    action_data_no_attributes = {
        "entity_id": "switch.fan",
        "domain": "switch",
        "action": "toggle",
    }
    action_no_attributes = SmartHomeAction(**action_data_no_attributes)
    assert action_no_attributes.model_dump() == {
        **action_data_no_attributes,
        "attributes": None,
    }


def test_smart_home_action_validation_errors():
    """
    Test SmartHomeAction raises validation errors for invalid input.
    """
    # Invalid action
    with pytest.raises(ValidationError):
        SmartHomeAction(
            entity_id="light.bad", domain="light", action="bad_action"
        )
    # Missing required field
    with pytest.raises(ValidationError):
        SmartHomeAction(domain="light", action="on")


def test_laptop_system_action_serialization_and_defaults():
    """
    Test LaptopSystemAction serialization and default values.
    """
    action_data = {"command": "notepad.exe", "action_type": "launch"}
    action = LaptopSystemAction(**action_data)
    assert action.model_dump() == {**action_data, "timeout_sec": 10}

    action_with_timeout = {
        "command": "dir /s",
        "action_type": "terminal",
        "timeout_sec": 60,
    }
    action = LaptopSystemAction(**action_with_timeout)
    assert action.model_dump() == action_with_timeout


def test_laptop_system_action_validation_errors():
    """
    Test LaptopSystemAction raises validation errors for invalid input.
    """
    # Invalid action_type
    with pytest.raises(ValidationError):
        LaptopSystemAction(command="cmd", action_type="invalid")
    # Missing required field
    with pytest.raises(ValidationError):
        LaptopSystemAction(action_type="launch")


def test_browser_action_serialization():
    """
    Test BrowserAction can be serialized correctly.
    """
    action_data = {
        "url": "https://example.com",
        "action": "goto",
        "selector": None,
    }
    action = BrowserAction(**action_data)
    assert action.model_dump() == action_data

    action_with_selector = {
        "url": "https://example.com/login",
        "action": "click",
        "selector": "#loginButton",
    }
    action = BrowserAction(**action_with_selector)
    assert action.model_dump() == action_with_selector


def test_browser_action_validation_errors():
    """
    Test BrowserAction raises validation errors for invalid input.
    """
    # Invalid action
    with pytest.raises(ValidationError):
        BrowserAction(url="https://example.com", action="bad_action")
    # Missing required field
    with pytest.raises(ValidationError):
        BrowserAction(action="goto", selector=".some_selector")


def test_voice_command_payload_serialization():
    """
    Test VoiceCommandPayload can be serialized correctly.
    """
    payload_data = {
        "raw_transcript": "turn on the lights",
        "confidence": 0.95,
        "timestamp": "2023-10-27T10:00:00Z",
    }
    payload = VoiceCommandPayload(**payload_data)
    assert payload.model_dump() == payload_data


def test_voice_command_payload_validation_errors():
    """
    Test VoiceCommandPayload raises validation errors for invalid input.
    """
    # Invalid confidence type
    with pytest.raises(ValidationError):
        VoiceCommandPayload(
            raw_transcript="hello", confidence="high", timestamp="now"
        )
    # Missing required field
    with pytest.raises(ValidationError):
        VoiceCommandPayload(confidence=0.8, timestamp="now")


def test_agent_execution_result_serialization():
    """
    Test AgentExecutionResult can be serialized correctly.
    """
    result_data = {
        "success": True,
        "tool_name": "smart_home",
        "output_payload": {"status": "ok", "message": "light turned on"},
        "error": None,
    }
    result = AgentExecutionResult(**result_data)
    assert result.model_dump() == result_data

    result_with_error = {
        "success": False,
        "tool_name": "browser_tool",
        "output_payload": {},
        "error": "Selector not found",
    }
    result = AgentExecutionResult(**result_with_error)
    assert result.model_dump() == result_with_error


def test_agent_execution_result_validation_errors():
    """
    Test AgentExecutionResult raises validation errors for invalid input.
    """
    # Invalid success type
    with pytest.raises(ValidationError):
        AgentExecutionResult(
            success="yes",
            tool_name="tool",
            output_payload={},
            error="message",
        )
    # Missing required field
    with pytest.raises(ValidationError):
        AgentExecutionResult(
            tool_name="tool",
            output_payload={"status": "failed"},
            error="error",
        )
