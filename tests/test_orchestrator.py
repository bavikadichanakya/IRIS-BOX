import json
import unittest
from unittest.mock import patch, MagicMock

from pydantic import BaseModel

from src.agent.orchestrator import IRISOrchestrator
from src.models.schemas import AgentExecutionResult
from src.tools.registry import BaseTool, ToolRegistry


class DummyPayload(BaseModel):
    """A dummy payload for testing."""
    value: str


class DummyTool(BaseTool):
    """A dummy tool for testing."""
    def execute(self, payload: DummyPayload) -> AgentExecutionResult:
        return AgentExecutionResult(
            success=True,
            tool_name="DummyTool",
            output_payload={"result": f"Processed: {payload.value}"}
        )


class TestIRISOrchestrator(unittest.TestCase):

    def setUp(self):
        # Reset the tool registry to avoid interference from other tests
        ToolRegistry._tool_classes = {}
        # Register the dummy tool
        ToolRegistry._tool_classes["DummyTool"] = DummyTool

    def test_get_tool_schemas(self):
        orchestrator = IRISOrchestrator(api_base="http://mock", api_key="mock")
        schemas = orchestrator._get_tool_schemas()
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["name"], "DummyTool")
        # Check that the payload model is stored
        self.assertIn("DummyTool", orchestrator._payload_models)
        self.assertEqual(orchestrator._payload_models["DummyTool"], DummyPayload)

    @patch('openai.OpenAI')
    def test_process_request_success(self, mock_openai):
        # Setup the mock LLM response
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_function_call = MagicMock()
        mock_function_call.name = "DummyTool"
        mock_function_call.arguments = json.dumps({"value": "test"})
        mock_message.function_call = mock_function_call
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        orchestrator = IRISOrchestrator(api_base="http://mock", api_key="mock")
        result = orchestrator.process_request("test prompt")

        self.assertTrue(result.success)
        self.assertEqual(result.tool_name, "DummyTool")
        self.assertEqual(result.output_payload, {"result": "Processed: test"})

    @patch('openai.OpenAI')
    def test_process_request_no_function_call(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Hello user"
        mock_message.tool_calls = None
        mock_message.function_call = None
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        orchestrator = IRISOrchestrator(api_base="http://mock", api_key="mock")
        result = orchestrator.process_request("test prompt")

        self.assertTrue(result.success)
        self.assertEqual(result.output_payload, {"response": "Hello user"})

    @patch('openai.OpenAI')
    def test_process_request_invalid_arguments(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_function_call = MagicMock()
        mock_function_call.name = "DummyTool"
        mock_function_call.arguments = json.dumps({"invalid_key": "test"})  # missing required 'value'
        mock_message.function_call = mock_function_call
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        orchestrator = IRISOrchestrator(api_base="http://mock", api_key="mock")
        result = orchestrator.process_request("test prompt")

        self.assertFalse(result.success)
        self.assertIn("Failed to parse function arguments", result.error)

    @patch('openai.OpenAI')
    def test_process_request_protected_tool_policy(self, mock_openai):
        class DummyHomePayload(BaseModel):
            entity_id: str

        class HomeAssistantTool(BaseTool):
            def execute(self, payload: DummyHomePayload) -> AgentExecutionResult:
                return AgentExecutionResult(success=True, tool_name="HomeAssistantTool", output_payload={"status": "ok"})

        ToolRegistry._tool_classes["HomeAssistantTool"] = HomeAssistantTool

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_function_call = MagicMock()
        mock_function_call.name = "HomeAssistantTool"
        mock_function_call.arguments = json.dumps({"entity_id": "light.living_room"})
        mock_message.function_call = mock_function_call
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        orchestrator = IRISOrchestrator(api_base="http://mock", api_key="mock")

        # 1. Reject when device_id is unknown/missing
        res_denied = orchestrator.process_request("turn on light", device_id="unknown")
        self.assertFalse(res_denied.success)
        self.assertIn("requires a verified device_id", res_denied.error)

        # 2. Allow when device_id is verified
        res_allowed = orchestrator.process_request("turn on light", device_id="device-123")
        self.assertTrue(res_allowed.success)
        self.assertEqual(res_allowed.output_payload, {"status": "ok"})

    @patch('openai.OpenAI')
    def test_process_request_sensitive_tool_policy(self, mock_openai):
        class DummySysPayload(BaseModel):
            command: str

        class SystemCommandTool(BaseTool):
            def execute(self, payload: DummySysPayload) -> AgentExecutionResult:
                return AgentExecutionResult(success=True, tool_name="SystemCommandTool", output_payload={"stdout": "hello"})

        ToolRegistry._tool_classes["SystemCommandTool"] = SystemCommandTool

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_function_call = MagicMock()
        mock_function_call.name = "SystemCommandTool"
        mock_function_call.arguments = json.dumps({"command": "echo hello"})
        mock_message.function_call = mock_function_call
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        orchestrator = IRISOrchestrator(api_base="http://mock", api_key="mock")

        # 1. Denied when confirmation_token is missing (returns token and pending action)
        res_denied = orchestrator.process_request("echo hello")
        self.assertFalse(res_denied.success)
        self.assertIn("CONFIRMATION_REQUIRED", res_denied.error)
        self.assertIsNotNone(res_denied.confirmation_token)
        self.assertIsNotNone(res_denied.pending_action)

        # 2. Allowed when valid confirmation_token is provided
        token = res_denied.confirmation_token
        res_allowed = orchestrator.process_request("echo hello", confirmation_token=token)
        self.assertTrue(res_allowed.success)
        self.assertEqual(res_allowed.output_payload, {"stdout": "hello"})


if __name__ == '__main__':
    unittest.main()
