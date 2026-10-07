import json
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient

from src.server.app import app
from src.models.schemas import AgentExecutionResult, VoiceCommandPayload


@pytest.fixture
def mock_orchestrator():
    mock = Mock()
    mock_result = AgentExecutionResult(success=True, tool_name="test", output_payload={"result": "ok"})
    mock.process_request.return_value = mock_result
    app.state.orchestrator = mock
    yield mock
    # Cleanup
    if hasattr(app.state, "orchestrator"):
        del app.state.orchestrator


def test_health_check():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_websocket_valid_payload(mock_orchestrator):
    client = TestClient(app)
    with client.websocket_connect("/ws/voice-stream") as websocket:
        payload = {
            "raw_transcript": "test transcript",
            "confidence": 0.9,
            "timestamp": "2023-01-01T00:00:00Z"
        }
        websocket.send_json(payload)
        response = websocket.receive_json()
        assert response == mock_orchestrator.process_request.return_value.model_dump()
        mock_orchestrator.process_request.assert_called_once_with("test transcript")


def test_websocket_invalid_json(mock_orchestrator):
    client = TestClient(app)
    with client.websocket_connect("/ws/voice-stream") as websocket:
        websocket.send_text("invalid json")
        response = websocket.receive_json()
        assert "error" in response
        assert response["error"] == "Invalid JSON"


def test_websocket_invalid_payload(mock_orchestrator):
    client = TestClient(app)
    with client.websocket_connect("/ws/voice-stream") as websocket:
        # Missing required fields
        payload = {"raw_transcript": "test"}
        websocket.send_json(payload)
        response = websocket.receive_json()
        assert "error" in response
        assert "Invalid payload" in response["error"]


def test_websocket_orchestrator_not_initialized():
    # Remove orchestrator if set
    if hasattr(app.state, "orchestrator"):
        del app.state.orchestrator
    client = TestClient(app)
    with client.websocket_connect("/ws/voice-stream") as websocket:
        payload = {
            "raw_transcript": "test transcript",
            "confidence": 0.9,
            "timestamp": "2023-01-01T00:00:00Z"
        }
        websocket.send_json(payload)
        response = websocket.receive_json()
        assert "error" in response
        assert response["error"] == "Orchestrator not initialized"
