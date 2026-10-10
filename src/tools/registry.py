import asyncio
import functools
import inspect
import os
import shlex
import subprocess
from typing import Callable, Dict, Any, Type, List

import requests
from pydantic import BaseModel

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

    @classmethod
    def get_schemas(cls) -> List[Dict[str, Any]]:
        """
        Returns a list of tool schema dictionaries for all registered tools.
        """
        schemas = []
        for name, tool_class in cls._tool_classes.items():
            sig = inspect.signature(tool_class.execute)
            params = list(sig.parameters.values())
            if len(params) < 2:
                continue
            payload_param = params[1]
            payload_type = payload_param.annotation
            if isinstance(payload_type, type) and issubclass(payload_type, BaseModel):
                schema = payload_type.model_json_schema()
                description = tool_class.__doc__ or f"Execute {name} action"
                schemas.append({
                    "name": name,
                    "description": description.strip(),
                    "parameters": {
                        "type": "object",
                        "properties": schema.get("properties", {}),
                        "required": schema.get("required", []),
                    },
                    "category": getattr(tool_class, "category", "general")
                })
        return schemas

    @classmethod
    async def execute(cls, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Executes a registered tool by name with arguments.
        """
        tool_class = cls._tool_classes.get(name)
        if not tool_class:
            raise ValueError(f"Tool '{name}' not found in registry.")

        sig = inspect.signature(tool_class.execute)
        params = list(sig.parameters.values())
        if len(params) >= 2:
            payload_param = params[1]
            payload_type = payload_param.annotation
            if isinstance(arguments, payload_type):
                payload = arguments
            elif isinstance(arguments, dict) and isinstance(payload_type, type) and issubclass(payload_type, BaseModel):
                payload = payload_type(**arguments)
            else:
                payload = arguments
        else:
            payload = arguments

        tool = cls.get_tool(name)
        if hasattr(tool, "execute_async") and callable(getattr(tool, "execute_async")):
            res = await tool.execute_async(payload)
        else:
            res = tool.execute(payload)
            if inspect.isawaitable(res):
                res = await res
        return res


@ToolRegistry.register_tool("HomeAssistantTool")
class HomeAssistantTool(BaseTool):
    """
    Dispatches local REST requests to Home Assistant with token auth.
    """
    def __init__(self, ha_url: str = "", ha_token: str = ""):
        env_ha_url = os.environ.get("HA_URL", "")
        env_ha_token = os.environ.get("HA_TOKEN", "")
        self.ha_url = ha_url or env_ha_url
        self.ha_token = ha_token or env_ha_token
        self.headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json",
        }

    def execute(self, action_payload: SmartHomeAction) -> AgentExecutionResult:
        if not self.ha_url or not self.ha_token:
            return AgentExecutionResult(
                success=False,
                tool_name="HomeAssistantTool",
                output_payload={},
                error="Home Assistant unavailable: credentials missing or connection refused",
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
        except Exception:
            return AgentExecutionResult(
                success=False,
                tool_name="HomeAssistantTool",
                output_payload={},
                error="Home Assistant unavailable: credentials missing or connection refused",
            )


@ToolRegistry.register_tool("SystemCommandTool")
class SystemCommandTool(BaseTool):
    """
    Safe local command executor with a whitelist of allowed commands.
    Uses shell=False with argument array tokenization for security.
    """
    _ALLOWED_COMMANDS = {
        "dir", "ls", "echo", "pwd", "cd", "sleep",
        "whoami", "hostname", "ipconfig", "ifconfig", "ping",
    }

    def execute(self, action_payload: LaptopSystemAction) -> AgentExecutionResult:
        from src.security.policy import validate_system_command
        
        valid, reason = validate_system_command(action_payload.command, list(self._ALLOWED_COMMANDS))
        if not valid:
            return AgentExecutionResult(
                success=False,
                tool_name="SystemCommandTool",
                output_payload={},
                error=f"SECURITY_DENIED: {reason}",
            )

        try:
            command_args = shlex.split(action_payload.command)
        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name="SystemCommandTool",
                output_payload={},
                error=f"Invalid command format: {e}",
            )

        if not command_args:
            return AgentExecutionResult(
                success=False,
                tool_name="SystemCommandTool",
                output_payload={},
                error="Empty command.",
            )

        base_command = command_args[0]
        if base_command not in self._ALLOWED_COMMANDS:
            return AgentExecutionResult(
                success=False,
                tool_name="SystemCommandTool",
                output_payload={},
                error=f"Command '{base_command}' is not in the allowed list.",
            )

        exec_args = list(command_args)
        if os.name == "nt" and base_command.lower() in {"echo", "dir", "cd", "cls", "type", "pwd"}:
            exec_args = ["cmd.exe", "/c"] + exec_args

        try:
            result = subprocess.run(
                exec_args,
                shell=False,
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
    Headless browser helper interface using Playwright.
    """
    def __init__(self, headless: bool = True):
        self.headless = headless

    def execute(self, action_payload: BrowserAction) -> AgentExecutionResult:
        from src.security.policy import is_url_allowed

        if action_payload.url:
            allowed, reason = is_url_allowed(action_payload.url)
            if not allowed:
                return AgentExecutionResult(
                    success=False,
                    tool_name="BrowserTool",
                    output_payload={},
                    error=f"SSRF_BLOCKED: {reason}"
                )

        try:
            return asyncio.run(self.execute_async(action_payload))
        except Exception:
            return AgentExecutionResult(
                success=False,
                tool_name="BrowserTool",
                output_payload={},
                error="Playwright is not installed or headless browser binary is missing. Install via 'playwright install'."
            )

    async def execute_async(self, action_payload: BrowserAction) -> AgentExecutionResult:
        from src.security.policy import is_url_allowed

        if action_payload.url:
            allowed, reason = is_url_allowed(action_payload.url)
            if not allowed:
                return AgentExecutionResult(
                    success=False,
                    tool_name="BrowserTool",
                    output_payload={},
                    error=f"SSRF_BLOCKED: {reason}"
                )

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return AgentExecutionResult(
                success=False,
                tool_name="BrowserTool",
                output_payload={},
                error="Playwright is not installed or headless browser binary is missing. Install via 'playwright install'."
            )

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                page = await browser.new_page()
                timeout = action_payload.timeout_ms
                act = action_payload.action
                output = {"action_performed": act, "url": action_payload.url or ""}

                if act in ("goto", "navigate"):
                    if not action_payload.url:
                        return AgentExecutionResult(success=False, tool_name="BrowserTool", error="URL is required for navigate action")
                    await page.goto(action_payload.url, timeout=timeout)
                    output["title"] = await page.title()
                elif act == "click":
                    if action_payload.url:
                        await page.goto(action_payload.url, timeout=timeout)
                    if not action_payload.selector:
                        return AgentExecutionResult(success=False, tool_name="BrowserTool", error="Selector is required for click action")
                    await page.click(action_payload.selector, timeout=timeout)
                    output["selector"] = action_payload.selector
                elif act == "type_text":
                    if action_payload.url:
                        await page.goto(action_payload.url, timeout=timeout)
                    if not action_payload.selector:
                        return AgentExecutionResult(success=False, tool_name="BrowserTool", error="Selector is required for type_text action")
                    await page.fill(action_payload.selector, action_payload.input_text or "", timeout=timeout)
                    output["selector"] = action_payload.selector
                    output["input_text"] = action_payload.input_text
                elif act in ("extract", "extract_text"):
                    if action_payload.url:
                        await page.goto(action_payload.url, timeout=timeout)
                    sel = action_payload.selector or "body"
                    content = await page.inner_text(sel, timeout=timeout)
                    output["extracted_content"] = content
                    if action_payload.selector:
                        output["selector"] = action_payload.selector
                elif act == "screenshot":
                    if action_payload.url:
                        await page.goto(action_payload.url, timeout=timeout)
                    import base64
                    screenshot_bytes = await page.screenshot(type="png", timeout=timeout)
                    output["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode("utf-8")

                await browser.close()
                return AgentExecutionResult(success=True, tool_name="BrowserTool", output_payload=output)
        except Exception:
            return AgentExecutionResult(
                success=False,
                tool_name="BrowserTool",
                output_payload={},
                error="Playwright is not installed or headless browser binary is missing. Install via 'playwright install'."
            )
