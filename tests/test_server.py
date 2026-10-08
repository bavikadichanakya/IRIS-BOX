import json
from unittest.mock import Mock, patch

import pytest
from starlette.testclient import TestClient
from fastapi import FastAPI

from src.server.app import app, lifespan
from src.models.schemas import AgentExecutionResult, VoiceCommandPayload
from src.agent.orchestrator import IRISOrchestrator


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


def test_websocket_ping_pong(mock_orchestrator):
    client = TestClient(app)
    with client.websocket_connect("/ws/voice-stream") as websocket:
        websocket.send_json({"type": "ping"})
        response = websocket.receive_json()
        assert response == {"type": "pong"}


def test_lifespan_startup():
    """Test that lifespan properly initializes the orchestrator."""
    test_app = FastAPI(lifespan=lifespan)
    
    with patch.dict('os.environ', {
        'OPENAI_API_BASE': 'https://test.example.com',
        'OPENROUTER_API_KEY': 'test_key',
        'OPENAI_MODEL': 'test-model'
    }):
        with patch('src.server.app.IRISOrchestrator') as mock_orchestrator_class:
            mock_instance = Mock()
            mock_orchestrator_class.return_value = mock_instance
            
            with TestClient(test_app) as client:
                assert test_app.state.orchestrator is mock_instance
                mock_orchestrator_class.assert_called_once_with(
                    api_base='https://test.example.com',
                    api_key='test_key',
                    model='test-model'
                )
