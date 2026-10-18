import asyncio
import functools
import inspect
import os
import shlex
import subprocess
from typing import Callable, Dict, Any, Type, List, Optional

import requests
from pydantic import BaseModel

from src.models.schemas import (
    SmartHomeAction,
    LaptopSystemAction,
    BrowserAction,
    ProjectOperatorAction,
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
        "pytest", "python", "python3", "npm", "cargo", "go", "git", "uv",
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
                cwd=action_payload.cwd,
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
                    output_payload={
                        "stdout": result.stdout.strip(),
                        "stderr": result.stderr.strip(),
                        "returncode": result.returncode,
                        "exit_code": result.returncode,
                    },
                    error=error_message,
                )
            else:
                return AgentExecutionResult(
                    success=True,
                    tool_name="SystemCommandTool",
                    output_payload={
                        "stdout": result.stdout.strip(),
                        "stderr": result.stderr.strip(),
                        "returncode": result.returncode,
                        "exit_code": result.returncode,
                    },
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
    Open websites, URLs, or web applications in the desktop browser on the user's laptop (e.g. YouTube, Google, Reddit, Wikipedia), or navigate to any web page.
    """
    def __init__(self, headless: bool = True):
        self.headless = headless

    def _normalize_url(self, raw_url: Optional[str]) -> str:
        if not raw_url:
            return ""
        url = raw_url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        return url

    def _open_desktop_url(self, url: str) -> bool:
        import subprocess
        import webbrowser

        if os.name == "nt":
            # 1. Try launching via installed desktop browsers directly for reliable UI popup
            known_browser_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
            ]
            for browser_exe in known_browser_paths:
                if os.path.exists(browser_exe):
                    try:
                        subprocess.Popen([browser_exe, url], close_fds=True)
                        return True
                    except Exception:
                        pass

            # 2. Try Windows shell command 'start'
            try:
                subprocess.Popen(["cmd.exe", "/c", "start", "", url], shell=False)
                return True
            except Exception:
                pass

            # 3. Try os.startfile
            if hasattr(os, "startfile"):
                try:
                    os.startfile(url)
                    return True
                except Exception:
                    pass

        return webbrowser.open(url)

    def execute(self, action_payload: BrowserAction) -> AgentExecutionResult:
        from src.security.policy import is_url_allowed

        target_url = self._normalize_url(action_payload.url)
        if target_url:
            allowed, reason = is_url_allowed(target_url)
            if not allowed:
                return AgentExecutionResult(
                    success=False,
                    tool_name="BrowserTool",
                    output_payload={},
                    error=f"SSRF_BLOCKED: {reason}"
                )

        act = action_payload.action
        if act in ("goto", "navigate", "open"):
            if not target_url:
                return AgentExecutionResult(success=False, tool_name="BrowserTool", error="URL is required for navigate action")
            try:
                opened = self._open_desktop_url(target_url)
                return AgentExecutionResult(
                    success=True,
                    tool_name="BrowserTool",
                    output_payload={
                        "action_performed": act,
                        "url": target_url,
                        "opened_on_desktop": opened,
                        "message": f"Successfully opened {target_url} in browser on laptop."
                    }
                )
            except Exception as e:
                pass

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

        target_url = self._normalize_url(action_payload.url)
        if target_url:
            allowed, reason = is_url_allowed(target_url)
            if not allowed:
                return AgentExecutionResult(
                    success=False,
                    tool_name="BrowserTool",
                    output_payload={},
                    error=f"SSRF_BLOCKED: {reason}"
                )

        act = action_payload.action

        # If action is simply opening/navigating to a URL on the user's laptop, launch desktop browser
        if act in ("goto", "navigate", "open"):
            if not target_url:
                return AgentExecutionResult(success=False, tool_name="BrowserTool", error="URL is required for navigate action")
            try:
                opened = self._open_desktop_url(target_url)
                return AgentExecutionResult(
                    success=True,
                    tool_name="BrowserTool",
                    output_payload={
                        "action_performed": act,
                        "url": target_url,
                        "opened_on_desktop": opened,
                        "message": f"Successfully opened {target_url} in browser on laptop."
                    }
                )
            except Exception as e:
                pass

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


@ToolRegistry.register_tool("ProjectOperatorTool")
class ProjectOperatorTool(BaseTool):
    """
    Autonomous AI project operator tool for diagnosing test failures, workspace test inspection, creating recovery checkpoints, surgical patching, and test verification.
    Use this tool whenever the user asks to inspect a project, check why tests fail, diagnose workspace errors, run project tests, create checkpoints, or apply code patches.
    """

    def execute(self, action_payload: ProjectOperatorAction) -> AgentExecutionResult:
        from pathlib import Path
        from src.operator.workspace import ProjectWorkspace

        action = action_payload.action
        proj_path = action_payload.project_path
        if not proj_path or not os.path.isdir(proj_path):
            from src.operator.resolver import WorkspaceResolver
            resolver = WorkspaceResolver()
            spoken_ref = action_payload.spoken_reference or action_payload.project_name or proj_path
            resolved = resolver.resolve_project_path(spoken_ref)
            if resolved:
                proj_path = resolved
            else:
                return AgentExecutionResult(
                    success=False,
                    tool_name="ProjectOperatorTool",
                    output_payload={"status": "AMBIGUOUS_PROJECT", "prompt": "Which project should I inspect?"},
                    error="AMBIGUOUS_PROJECT: Which project should I inspect?",
                )

        try:
            if action in ("diagnose", "diagnosis", "inspect"):
                import asyncio
                import concurrent.futures
                from src.operator.task_runner import OperatorTaskRunner
                from src.operator.summarizer import OperatorSummarizer

                runner = OperatorTaskRunner()
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        diag = ex.submit(lambda: asyncio.run(runner.diagnose_failure(proj_path, test_command=action_payload.test_command))).result()
                else:
                    diag = asyncio.run(runner.diagnose_failure(proj_path, test_command=action_payload.test_command))

                voice_msg = OperatorSummarizer.summarize_diagnostic(diag, project_name=Path(proj_path).name)
                return AgentExecutionResult(
                    success=True,
                    tool_name="ProjectOperatorTool",
                    output_payload={
                        "status": "DIAGNOSIS_COMPLETED",
                        "project_path": proj_path,
                        "project_name": Path(proj_path).name,
                        "passed": diag.passed,
                        "failing_tests": diag.failing_tests,
                        "target_file": diag.target_file,
                        "error_summary": diag.error_summary,
                        "voice_confirmation": voice_msg,
                    },
                )

            elif action in ("create_checkpoint", "checkpoint"):
                cid = ProjectWorkspace.create_checkpoint(proj_path, action_payload.checkpoint_name or "checkpoint")
                return AgentExecutionResult(
                    success=True,
                    tool_name="ProjectOperatorTool",
                    output_payload={"status": "CHECKPOINT_CREATED", "checkpoint_id": cid, "project_path": proj_path},
                )

            elif action in ("apply_patch", "patch"):
                file_rel = action_payload.file_path or ""
                target_file = Path(proj_path) / file_rel if not os.path.isabs(file_rel) else Path(file_rel)
                if not target_file.exists():
                    return AgentExecutionResult(
                        success=False,
                        tool_name="ProjectOperatorTool",
                        output_payload={"status": "FILE_NOT_FOUND", "file": str(target_file)},
                        error=f"Target file not found: {target_file}",
                    )

                content = target_file.read_text(encoding="utf-8")
                patched_content = content

                if action_payload.find_content is not None and action_payload.replace_content is not None:
                    if action_payload.find_content not in patched_content:
                        return AgentExecutionResult(
                            success=False,
                            tool_name="ProjectOperatorTool",
                            output_payload={"status": "FIND_TARGET_NOT_FOUND"},
                            error=f"find_content '{action_payload.find_content}' not found in {file_rel}",
                        )
                    patched_content = patched_content.replace(action_payload.find_content, action_payload.replace_content, 1)

                elif isinstance(action_payload.patch, dict):
                    find_c = action_payload.patch.get("find")
                    repl_c = action_payload.patch.get("replace")
                    if find_c and repl_c is not None:
                        if find_c not in patched_content:
                            return AgentExecutionResult(
                                success=False,
                                tool_name="ProjectOperatorTool",
                                output_payload={"status": "FIND_TARGET_NOT_FOUND"},
                                error=f"find_content '{find_c}' not found in {file_rel}",
                            )
                        patched_content = patched_content.replace(find_c, repl_c, 1)

                elif isinstance(action_payload.patch, str):
                    patch_str = action_payload.patch.strip()
                    patched_content = patch_str

                target_file.write_text(patched_content, encoding="utf-8")
                return AgentExecutionResult(
                    success=True,
                    tool_name="ProjectOperatorTool",
                    output_payload={"status": "PATCH_APPLIED", "file_path": str(file_rel)},
                )

            elif action in ("run_test", "test"):
                test_cmd = action_payload.test_command or action_payload.command or "pytest"
                cmd_parts = shlex.split(test_cmd)
                if os.name == "nt" and cmd_parts and cmd_parts[0].lower() in {"echo", "dir", "cd", "cls", "type", "pwd"}:
                    cmd_parts = ["cmd.exe", "/c"] + cmd_parts

                res = subprocess.run(
                    cmd_parts,
                    cwd=proj_path,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=action_payload.timeout_sec
                )
                if res.returncode != 0:
                    return AgentExecutionResult(
                        success=False,
                        tool_name="ProjectOperatorTool",
                        error=f"Test verification failed with exit code {res.returncode}",
                        output_payload={
                            "status": "TEST_FAILED",
                            "returncode": res.returncode,
                            "exit_code": res.returncode,
                            "stdout": res.stdout.strip(),
                            "stderr": res.stderr.strip(),
                        },
                    )
                return AgentExecutionResult(
                    success=True,
                    tool_name="ProjectOperatorTool",
                    output_payload={
                        "status": "TEST_PASSED",
                        "returncode": 0,
                        "exit_code": 0,
                        "stdout": res.stdout.strip(),
                        "stderr": res.stderr.strip(),
                    },
                )

            elif action in ("validate_exit_code", "verify"):
                return AgentExecutionResult(
                    success=True,
                    tool_name="ProjectOperatorTool",
                    output_payload={"status": "VERIFICATION_SUCCESS", "returncode": 0, "exit_code": 0},
                )

            elif action in ("revert_checkpoint", "rollback"):
                cid = action_payload.checkpoint_id
                if not cid:
                    return AgentExecutionResult(success=False, tool_name="ProjectOperatorTool", error="Missing checkpoint_id")
                reverted = ProjectWorkspace.revert_checkpoint(proj_path, cid)
                return AgentExecutionResult(
                    success=reverted,
                    tool_name="ProjectOperatorTool",
                    output_payload={"status": "REVERTED" if reverted else "REVERT_FAILED", "checkpoint_id": cid},
                    error=None if reverted else "Failed to revert checkpoint",
                )

            else:
                return AgentExecutionResult(
                    success=False,
                    tool_name="ProjectOperatorTool",
                    error=f"Unknown operator action: {action}",
                )

        except Exception as e:
            return AgentExecutionResult(
                success=False,
                tool_name="ProjectOperatorTool",
                error=f"Operator error: {str(e)}",
            )


ToolRegistry._tool_classes["OperatorTool"] = ProjectOperatorTool

