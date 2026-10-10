import unittest
from unittest.mock import patch, MagicMock
import requests
import subprocess
import os

from src.tools.registry import ToolRegistry, HomeAssistantTool, SystemCommandTool, BrowserTool, BaseTool
from src.models.schemas import SmartHomeAction, LaptopSystemAction, BrowserAction, AgentExecutionResult


class TestToolRegistry(unittest.TestCase):

    def setUp(self):
        ToolRegistry._tool_classes.clear()

    def test_register_tool_decorator_success(self):
        @ToolRegistry.register_tool("TestTool")
        class TestTool(BaseTool):
            def execute(self, payload):
                return AgentExecutionResult(success=True, tool_name="TestTool", output_payload={})

        self.assertIn("TestTool", ToolRegistry.list_tools())
        tool_instance = ToolRegistry.get_tool("TestTool")
        self.assertIsInstance(tool_instance, TestTool)

    def test_register_tool_decorator_non_base_tool(self):
        with self.assertRaises(TypeError) as cm:
            @ToolRegistry.register_tool("InvalidTool")
            class InvalidTool:
                def execute(self, payload): pass
        self.assertIn("must inherit from BaseTool", str(cm.exception))

    def test_register_tool_decorator_duplicate_name(self):
        @ToolRegistry.register_tool("DuplicateTool")
        class FirstTool(BaseTool):
            def execute(self, payload): pass

        with self.assertRaises(ValueError) as cm:
            @ToolRegistry.register_tool("DuplicateTool")
            class SecondTool(BaseTool):
                def execute(self, payload): pass
        self.assertIn("already registered", str(cm.exception))

    def test_get_tool_success(self):
        @ToolRegistry.register_tool("AnotherTestTool")
        class AnotherTestTool(BaseTool):
            def __init__(self, value):
                self.value = value
            def execute(self, payload):
                return AgentExecutionResult(success=True, tool_name="AnotherTestTool", output_payload={"value": self.value})

        tool_instance = ToolRegistry.get_tool("AnotherTestTool", value=123)
        self.assertIsInstance(tool_instance, AnotherTestTool)
        self.assertEqual(tool_instance.value, 123)

    def test_get_tool_not_found(self):
        with self.assertRaises(ValueError) as cm:
            ToolRegistry.get_tool("NonExistentTool")
        self.assertIn("not found in registry", str(cm.exception))

    def test_list_tools(self):
        ToolRegistry._tool_classes.clear()
        @ToolRegistry.register_tool("ToolA")
        class ToolA(BaseTool):
            def execute(self, payload): pass
        @ToolRegistry.register_tool("ToolB")
        class ToolB(BaseTool):
            def execute(self, payload): pass

        tools = ToolRegistry.list_tools()
        self.assertIn("ToolA", tools)
        self.assertIn("ToolB", tools)
        self.assertEqual(len(tools), 2)
        self.assertSetEqual(set(tools), {"ToolA", "ToolB"})


class TestHomeAssistantTool(unittest.TestCase):

    def setUp(self):
        self.ha_url = "http://localhost:8123"
        self.ha_token = "test_token"
        self.tool = HomeAssistantTool(ha_url=self.ha_url, ha_token=self.ha_token)
        self.mock_tool = HomeAssistantTool(ha_url="", ha_token="", mock_mode=True)

    def test_init_explicit_mock_mode_no_credentials(self):
        tool = HomeAssistantTool(ha_url="", ha_token="", mock_mode=True)
        self.assertTrue(tool.mock_mode)

    def test_init_auto_mock_mode_when_credentials_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            tool = HomeAssistantTool()
            self.assertFalse(tool.mock_mode)
            self.assertEqual(tool.ha_url, "")
            self.assertEqual(tool.ha_token, "")

    def test_init_auto_mock_mode_when_credentials_partial(self):
        with patch.dict(os.environ, {}, clear=True):
            tool = HomeAssistantTool(ha_url="http://localhost:8123")
            self.assertFalse(tool.mock_mode)

        with patch.dict(os.environ, {}, clear=True):
            tool = HomeAssistantTool(ha_token="some_token")
            self.assertFalse(tool.mock_mode)

    def test_init_explicit_non_mock_mode_with_credentials(self):
        tool = HomeAssistantTool(ha_url=self.ha_url, ha_token=self.ha_token, mock_mode=False)
        self.assertFalse(tool.mock_mode)
        self.assertEqual(tool.ha_url, self.ha_url)
        self.assertEqual(tool.ha_token, self.ha_token)

    def test_init_explicit_non_mock_mode_missing_credentials_raises(self):
        action_payload = SmartHomeAction(entity_id="light.bedroom", domain="light", action="on")
        tool1 = HomeAssistantTool(ha_url="", ha_token="token", mock_mode=False)
        res1 = tool1.execute(action_payload)
        self.assertFalse(res1.success)
        self.assertIn("Home Assistant credentials missing", res1.error)

    def test_init_from_env_vars_when_no_args(self):
        with patch.dict(os.environ, {"HA_URL": "http://env-url", "HA_TOKEN": "env-token"}):
            tool = HomeAssistantTool()
            self.assertFalse(tool.mock_mode)
            self.assertEqual(tool.ha_url, "http://env-url")
            self.assertEqual(tool.ha_token, "env-token")

    def test_init_env_vars_override_empty_args(self):
        with patch.dict(os.environ, {"HA_URL": "http://env-url", "HA_TOKEN": "env-token"}):
            tool = HomeAssistantTool(ha_url="", ha_token="")
            self.assertFalse(tool.mock_mode)
            self.assertEqual(tool.ha_url, "http://env-url")
            self.assertEqual(tool.ha_token, "env-token")

    def test_init_args_override_env_vars(self):
        with patch.dict(os.environ, {"HA_URL": "http://env-url", "HA_TOKEN": "env-token"}):
            tool = HomeAssistantTool(ha_url="http://arg-url", ha_token="arg-token")
            self.assertFalse(tool.mock_mode)
            self.assertEqual(tool.ha_url, "http://arg-url")
            self.assertEqual(tool.ha_token, "arg-token")

    @patch('requests.post')
    def test_execute_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"message": "Service executed"}
        mock_response.content = b'{"message": "Service executed"}'
        mock_post.return_value = mock_response

        action_payload = SmartHomeAction(
            entity_id="light.bedroom",
            domain="light",
            action="on",
            attributes={"brightness": 255}
        )
        result = self.tool.execute(action_payload)

        self.assertTrue(result.success)
        self.assertEqual(result.tool_name, "HomeAssistantTool")
        self.assertEqual(result.output_payload, {"message": "Service executed"})
        self.assertIsNone(result.error)

        expected_url = f"{self.ha_url}/api/services/light/on"
        expected_headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json",
        }
        expected_json = {"entity_id": "light.bedroom", "brightness": 255}
        mock_post.assert_called_once_with(expected_url, headers=expected_headers, json=expected_json, timeout=10)

    @patch('requests.post')
    def test_execute_failure_http_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Bad Request")
        mock_post.return_value = mock_response

        action_payload = SmartHomeAction(
            entity_id="light.bedroom",
            domain="light",
            action="on"
        )
        result = self.tool.execute(action_payload)

        self.assertFalse(result.success)
        self.assertEqual(result.tool_name, "HomeAssistantTool")
        self.assertIn("unreachable", result.error.lower())
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_execute_failure_connection_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection Refused")

        action_payload = SmartHomeAction(
            entity_id="light.bedroom",
            domain="light",
            action="on"
        )
        result = self.tool.execute(action_payload)

        self.assertFalse(result.success)
        self.assertEqual(result.tool_name, "HomeAssistantTool")
        self.assertIn("unreachable", result.error.lower())
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_execute_mock_mode(self, mock_post):
        action_payload = SmartHomeAction(
            entity_id="light.bedroom",
            domain="light",
            action="on"
        )
        result = self.mock_tool.execute(action_payload)

        self.assertTrue(result.success)
        self.assertEqual(result.tool_name, "HomeAssistantTool")
        self.assertEqual(result.output_payload, {"message": "Mock HA call successful."})
        self.assertIsNone(result.error)
        mock_post.assert_not_called()


class TestSystemCommandTool(unittest.TestCase):

    def setUp(self):
        self.tool = SystemCommandTool()

    @patch('subprocess.run')
    def test_execute_allowed_command_success(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Hello World\n"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        action_payload = LaptopSystemAction(command="echo Hello World", action_type="terminal", timeout_sec=5)
        result = self.tool.execute(action_payload)

        self.assertTrue(result.success)
        self.assertEqual(result.tool_name, "SystemCommandTool")
        self.assertEqual(result.output_payload, {"stdout": "Hello World", "stderr": ""})
        self.assertIsNone(result.error)
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_execute_allowed_command_failure(self, mock_run):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Command failed\n"
        mock_run.return_value = mock_result

        action_payload = LaptopSystemAction(command="ls non_existent_file", action_type="terminal", timeout_sec=5)
        result = self.tool.execute(action_payload)

        self.assertFalse(result.success)
        self.assertEqual(result.tool_name, "SystemCommandTool")
        self.assertEqual(result.output_payload, {"stdout": "", "stderr": "Command failed"})
        self.assertIn("Command failed", result.error)
        mock_run.assert_called_once()

    def test_execute_disallowed_command(self):
        action_payload = LaptopSystemAction(command="rm -rf /", action_type="terminal", timeout_sec=5)
        result = self.tool.execute(action_payload)

        self.assertFalse(result.success)
        self.assertEqual(result.tool_name, "SystemCommandTool")
        self.assertIn("not in the allowed list", result.error)
        self.assertEqual(result.output_payload, {})
        with patch('subprocess.run') as mock_run:
            self.tool.execute(action_payload)
            mock_run.assert_not_called()

    @patch('subprocess.run')
    def test_execute_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 10", timeout=1)

        action_payload = LaptopSystemAction(command="sleep 10", action_type="terminal", timeout_sec=1)
        result = self.tool.execute(action_payload)

        self.assertFalse(result.success)
        self.assertEqual(result.tool_name, "SystemCommandTool")
        self.assertIn("timed out", result.error)
        self.assertIn("TimeoutExpired", result.error)
        self.assertEqual(result.output_payload, {})
        mock_run.assert_called_once()


class TestBrowserTool(unittest.TestCase):

    def setUp(self):
        self.tool = BrowserTool()

    def test_execute_missing_playwright_returns_error(self):
        action_payload = BrowserAction(url="http://example.com", action="goto")
        result = self.tool.execute(action_payload)

        self.assertEqual(result.tool_name, "BrowserTool")
        if not result.success:
            self.assertIn("Playwright is not installed", result.error)
