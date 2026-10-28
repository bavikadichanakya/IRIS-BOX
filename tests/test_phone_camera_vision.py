import pytest
import base64
from unittest.mock import MagicMock, patch

from src.models.schemas import PhoneCameraVisionAction, AgentExecutionResult
from src.tools.registry import ToolRegistry
from src.vision.phone_camera import PhoneCameraManager, PhoneCameraTool


def test_phone_camera_manager_capture_fallback():
    manager = PhoneCameraManager()
    data = manager.capture_snapshot(camera_id="0")
    assert isinstance(data, bytes)
    assert len(data) > 0
    # Check JPEG SOI marker (0xFF, 0xD8)
    assert data[:2] == b"\xff\xd8"


def test_phone_camera_manager_analyze_mocked():
    manager = PhoneCameraManager()
    dummy_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"message": {"content": "I see a wooden desk with a notebook."}}'
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        desc = manager.analyze_image(dummy_bytes, "What is in front of the camera?")
        assert "wooden desk" in desc


def test_phone_camera_tool_execution():
    tool = PhoneCameraTool()
    action = PhoneCameraVisionAction(
        action="capture_and_inspect",
        question="What is in view?",
        camera_id="0",
    )

    with patch.object(tool.manager, "analyze_image", return_value="Desk with laptop and coffee cup."):
        result = tool.execute(action)
        assert isinstance(result, AgentExecutionResult)
        assert result.success is True
        assert result.tool_name == "PhoneCameraTool"
        assert result.output_payload["description"] == "Desk with laptop and coffee cup."
        assert result.output_payload["speech_reply"] == "Desk with laptop and coffee cup."
        assert result.output_payload["camera_id"] == "0"


def test_tool_registry_aliases():
    tool1 = ToolRegistry.get_tool("PhoneCameraTool")
    tool2 = ToolRegistry.get_tool("inspect_camera")
    assert isinstance(tool1, PhoneCameraTool)
    assert isinstance(tool2, PhoneCameraTool)

