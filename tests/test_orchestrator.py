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
        mock_message.function_call = None
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        orchestrator = IRISOrchestrator(api_base="http://mock", api_key="mock")
        result = orchestrator.process_request("test prompt")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "LLM did not return a function call.")

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
    def test_process_request_tool_not_found(self, mock_openai):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_function_call = MagicMock()
        mock_function_call.name = "NonExistentTool"
        mock_function_call.arguments = json.dumps({})
        mock_message.function_call = mock_function_call
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        orchestrator = IRISOrchestrator(api_base="http://mock", api_key="mock")
        result = orchestrator.process_request("test prompt")

        self.assertFalse(result.success)
        self.assertIn("Unknown tool", result.error)


if __name__ == '__main__':
    unittest.main()
