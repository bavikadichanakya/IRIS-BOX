import functools
import os
import subprocess
from typing import Callable, Dict, Any, Type, List

import requests

from src.models.schemas import (
    SmartHomeAction,
    LaptopSystemAction,
    BrowserAction,
    AgentExecutionResult,
)


class BaseTool:
    """Base class for all tools."""
    def execute(self, payload: Any) -> AgentExecutionResult:
        """
        Executes the tool's action with the given payload.
        Must be implemented by concrete tool classes.
        """
        raise NotImplementedError


class ToolRegistry:
    """
    A registry for managing and retrieving tool instances.
    """
    _tool_classes: Dict[str, Type[BaseTool]] = {} # Store registered tool classes

    @classmethod
    def register_tool(cls, name: str):
        """
        Decorator to register a tool class.
        """
        def decorator(tool_class: Type[BaseTool]):
            if not issubclass(tool_class, BaseTool):
                raise TypeError(f"Tool class {tool_class.__name__} must inherit from BaseTool.")
            if name in cls._tool_classes:
                raise ValueError(f"Tool with name '{name}' already registered.")
            cls._tool_classes[name] = tool_class
            return tool_class
        return decorator

    @classmethod
    def get_tool(cls, name: str, **kwargs) -> BaseTool:
        """
        Retrieves and instantiates a registered tool.
        """
        tool_class = cls._tool_classes.get(name)
        if not tool_class:
            raise ValueError(f"Tool '{name}' not found in registry.")
        return tool_class(**kwargs)

    @classmethod
    def list_tools(cls) -> List[str]:
        """
        Lists the names of all registered tools.
        """
        return list(cls._tool_classes.keys())


@ToolRegistry.register_tool("HomeAssistantTool")
class HomeAssistantTool(BaseTool):
    """
    Dispatches local REST requests to Home Assistant with token auth.
    Includes mock mode for testing without a live HA instance.
    """
    def __init__(self, ha_url: str = "", ha_token: str = "", mock_mode: bool = None):
        if mock_mode is None:
            # Auto-detect: default to True if HA_URL or HA_TOKEN env vars are missing/empty
            env_ha_url = os.environ.get("HA_URL", "")
            env_ha_token = os.environ.get("HA_TOKEN", "")
            if not ha_url:
                ha_url = env_ha_url
            if not ha_token:
                ha_token = env_ha_token
            mock_mode = not (ha_url and ha_token)
        
        if not mock_mode and (not ha_url or not ha_token):
            raise ValueError("HA URL and token must be provided unless in mock mode.")
        
        self.ha_url = ha_url
        self.ha_token = ha_token
        self.mock_mode = mock_mode
        self.headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json",
        }

    def execute(self, action_payload: SmartHomeAction) -> AgentExecutionResult:
        if self.mock_mode:
            return AgentExecutionResult(
                success=True,
                tool_name="HomeAssistantTool",
                output_payload={"message": "Mock HA call successful."},
            )

        try:
            service_url = f"{self.ha_url}/api/services/{action_payload.domain}/{action_payload.action}"
            data = {"entity_id": action_payload.entity_id}
            if action_payload.attributes:
                data.update(action_payload.attributes)

            response = requests.post(service_url, headers=self.headers, json=data, timeout=10)
            response.raise_for_status()

            return AgentExecutionResult(
                success=True,
                tool_name="HomeAssistantTool",
                output_payload=response.json() if response.content else {"message": "Service call successful"},
            )
        except requests.exceptions.RequestException as e:
            return AgentExecutionResult(
                success=False,
                tool_name="HomeAssistantTool",
                output_payload={},
                error=f"Home Assistant API error: {type(e).__name__}: {e}",
            )
        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name="HomeAssistantTool",
                output_payload={},
                error=f"An unexpected error occurred: {type(e).__name__}: {e}",
            )


@ToolRegistry.register_tool("SystemCommandTool")
class SystemCommandTool(BaseTool):
    """
    Safe local command executor with a whitelist of allowed commands.
    """
    _ALLOWED_COMMANDS = {
        "dir", "ls", "echo", "pwd", "cd", "sleep",
        "whoami", "hostname", "ipconfig", "ifconfig", "ping",
    }

    def execute(self, action_payload: LaptopSystemAction) -> AgentExecutionResult:
        command_parts = action_payload.command.split(maxsplit=1)
        base_command = command_parts[0]

        if base_command not in self._ALLOWED_COMMANDS:
            return AgentExecutionResult(
                success=False,
                tool_name="SystemCommandTool",
                output_payload={},
                error=f"Command '{base_command}' is not in the allowed list.",
            )

        try:
            # 'cd' command does not change the CWD of the Python process when run via subprocess.
            # The change only applies to the subprocess itself.
            if base_command == "cd":
                pass

            result = subprocess.run(
                action_payload.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=action_payload.timeout_sec,
                check=False
            )

            if result.returncode != 0:
                error_message = result.stderr.strip() if result.stderr.strip() else f"Command failed with exit code {result.returncode}"
                return AgentExecutionResult(
                    success=False,
                    tool_name="SystemCommandTool",
                    output_payload={"stdout": result.stdout.strip(), "stderr": result.stderr.strip()},
                    error=error_message,
                )
            else:
                return AgentExecutionResult(
                    success=True,
                    tool_name="SystemCommandTool",
                    output_payload={"stdout": result.stdout.strip(), "stderr": result.stderr.strip()},
                )
        except subprocess.TimeoutExpired as e:
            return AgentExecutionResult(
                success=False,
                tool_name="SystemCommandTool",
                output_payload={},
                error=f"Command timed out after {action_payload.timeout_sec} seconds. {type(e).__name__}: {e}",
            )
        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name="SystemCommandTool",
                output_payload={},
                error=f"An unexpected error occurred during command execution: {type(e).__name__}: {e}",
            )


@ToolRegistry.register_tool("BrowserTool")
class BrowserTool(BaseTool):
    """
    Headless browser helper interface. (Mock implementation)
    """
    def __init__(self):
        pass

    def execute(self, action_payload: BrowserAction) -> AgentExecutionResult:
        output = {"action_performed": action_payload.action, "url": action_payload.url}
        if action_payload.selector:
            output["selector"] = action_payload.selector

        if action_payload.action == "extract":
            output["extracted_content"] = f"Mock content from {action_payload.url}"
            if action_payload.selector:
                output["extracted_content"] += f" using selector {action_payload.selector}"

        return AgentExecutionResult(
            success=True,
            tool_name="BrowserTool",
            output_payload=output,
        )
