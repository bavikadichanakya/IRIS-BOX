import logging
import os
import shlex
import subprocess
import time
from typing import Any, Dict, Optional

from src.models.schemas import LaptopSystemAction
from src.security.policy import validate_system_command
from src.skills.base import BaseSkill, SkillExecutionResult, SkillHealthResult, SkillManifest
from src.tools.capability import PermissionLevel

logger = logging.getLogger("iris.skills.system_command")

_ALLOWED_COMMANDS = {
    "dir", "ls", "echo", "pwd", "cd", "sleep",
    "whoami", "hostname", "ipconfig", "ifconfig", "ping",
}


class SystemCommandSkill(BaseSkill):
    """
    Core skill executing whitelisted local system and terminal commands
    using safe argument arrays and shell=False.
    """

    def __init__(self, allowed_commands: Optional[set] = None):
        self.allowed_commands = allowed_commands or _ALLOWED_COMMANDS
        manifest = SkillManifest(
            name="SystemCommandSkill",
            version="1.0.0",
            description="Execute whitelisted system and terminal commands locally with strict tokenization.",
            category="system",
            permission_level=PermissionLevel.SENSITIVE,
            requires_network=False,
            timeout_seconds=15.0,
            parameters_schema=LaptopSystemAction.model_json_schema(),
            supported_platforms=["windows", "linux", "darwin"],
        )
        super().__init__(manifest)

    async def check_health(self) -> SkillHealthResult:
        """Verify operating system command shell availability."""
        shell_ok = False
        if os.name == "nt":
            shell_ok = os.path.exists(os.environ.get("COMSPEC", "C:\\Windows\\System32\\cmd.exe"))
        else:
            shell_ok = os.path.exists("/bin/sh") or os.path.exists("/bin/bash")

        return SkillHealthResult(
            skill_name=self.name,
            healthy=shell_ok,
            message="Local shell execution runtime ready" if shell_ok else "System shell binary not found",
            details={
                "os": os.name,
                "allowed_command_count": len(self.allowed_commands),
            }
        )

    async def execute(
        self,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> SkillExecutionResult:
        start_time = time.perf_counter()
        raw_cmd = params.get("command", "")
        timeout_sec = float(params.get("timeout_sec", 10.0))

        valid, reason = validate_system_command(raw_cmd, list(self.allowed_commands))
        if not valid:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=f"SECURITY_DENIED: {reason}",
                duration_ms=duration_ms
            )

        try:
            command_args = shlex.split(raw_cmd)
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=f"Invalid command format: {e}",
                duration_ms=duration_ms
            )

        if not command_args:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error="Empty command provided.",
                duration_ms=duration_ms
            )

        base_command = command_args[0]
        if base_command not in self.allowed_commands:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=f"Command '{base_command}' is not in the allowed list.",
                duration_ms=duration_ms
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
                timeout=timeout_sec,
                check=False
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            if result.returncode != 0:
                err_msg = result.stderr.strip() or f"Command exited with code {result.returncode}"
                return SkillExecutionResult(
                    success=False,
                    skill_name=self.name,
                    error=err_msg,
                    output={"stdout": result.stdout.strip(), "stderr": result.stderr.strip()},
                    duration_ms=duration_ms
                )
            return SkillExecutionResult(
                success=True,
                skill_name=self.name,
                output={"stdout": result.stdout.strip(), "returncode": result.returncode},
                duration_ms=duration_ms
            )
        except subprocess.TimeoutExpired:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=f"Command execution timed out after {timeout_sec}s",
                duration_ms=duration_ms
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=f"Command execution failed: {exc}",
                duration_ms=duration_ms
            )
