from __future__ import annotations
import os
import psutil
import subprocess
import shlex
import logging
from typing import Dict, Any, List

logger = logging.getLogger("iris.laptop_agent.system_control")

# Explicit command allowlist matching core SystemCommandTool policy
ALLOWED_BASE_COMMANDS = {
    "dir", "ls", "echo", "pwd", "cd", "sleep",
    "whoami", "hostname", "ipconfig", "ifconfig", "ping",
    "pytest", "python", "python3", "npm", "cargo", "go", "git", "uv",
}

# Forbidden shell chaining metacharacters when executing workstation commands
FORBIDDEN_SHELL_TOKENS = {";", "&&", "||", "|", "`", "$", "\n", "\r"}


class SystemControl:
    """
    Workstation telemetry, resource monitoring, and safe allowlisted command execution.
    Enforces least-privilege, agent-side validation, and argument tokenization with shell=False.
    """

    @staticmethod
    def get_status() -> Dict[str, Any]:
        """Collect host workstation telemetry."""
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        ram_pct = ram.percent
        ram_avail_gb = round(ram.available / (1024**3), 2)
        battery = psutil.sensors_battery()
        battery_pct = battery.percent if battery else None

        active_window = "Unknown"
        if os.name == "nt":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                if hwnd:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        active_window = buff.value.strip()
            except Exception:
                pass

        return {
            "success": True,
            "cpu_percent": cpu,
            "memory_percent": ram_pct,
            "available_ram_gb": ram_avail_gb,
            "battery_percent": battery_pct,
            "active_window": active_window,
            "message": f"CPU: {cpu}% | RAM: {ram_pct}% ({ram_avail_gb}GB free) | Active: '{active_window}'"
        }

    @staticmethod
    def run_command(command: str, timeout: float = 15.0) -> Dict[str, Any]:
        """
        Safely execute an allowlisted terminal command.
        Uses shell=False, strict tokenization, and rejects arbitrary shell execution.
        """
        if not command or not command.strip():
            return {"success": False, "error": "Empty command provided."}

        raw_cmd = command.strip()

        # Reject dangerous shell chaining metacharacters
        for tok in FORBIDDEN_SHELL_TOKENS:
            if tok in raw_cmd:
                logger.warning(f"Rejected command containing forbidden shell token '{tok}'")
                return {
                    "success": False,
                    "command": raw_cmd,
                    "error": f"SECURITY_DENIED: Chained shell commands containing '{tok}' are forbidden."
                }

        try:
            cmd_args = shlex.split(raw_cmd, posix=(os.name != "nt"))
        except Exception as e:
            return {"success": False, "command": raw_cmd, "error": f"Invalid command syntax: {e}"}

        if not cmd_args:
            return {"success": False, "error": "Parsed command arguments are empty."}

        base_cmd = os.path.basename(cmd_args[0]).lower().replace(".exe", "")
        if base_cmd not in ALLOWED_BASE_COMMANDS:
            logger.warning(f"Rejected non-allowlisted workstation command: '{base_cmd}'")
            return {
                "success": False,
                "command": raw_cmd,
                "error": (
                    f"SECURITY_DENIED: Command '{base_cmd}' is not in the workstation allowlist. "
                    f"Allowed commands: {sorted(list(ALLOWED_BASE_COMMANDS))}"
                )
            }

        try:
            # Execute strictly with shell=False
            res = subprocess.run(
                cmd_args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return {
                "success": res.returncode == 0,
                "command": raw_cmd,
                "exit_code": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "message": f"Command exited with code {res.returncode}"
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "command": raw_cmd, "error": f"Command timed out after {timeout}s"}
        except FileNotFoundError:
            return {"success": False, "command": raw_cmd, "error": f"Executable '{cmd_args[0]}' not found on host."}
        except Exception as exc:
            logger.error(f"Command execution error: {exc}")
            return {"success": False, "command": raw_cmd, "error": str(exc)}
