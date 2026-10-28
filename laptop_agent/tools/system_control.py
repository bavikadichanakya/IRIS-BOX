from __future__ import annotations
import os
import subprocess
import logging
from typing import Any, Dict, Optional

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger("iris.laptop_agent.system_control")


class SystemControl:
    """System observability, status monitoring, and shell command execution."""

    @staticmethod
    def get_status() -> Dict[str, Any]:
        """Collect instantaneous system metrics."""
        cpu = 0.0
        ram_pct = 0.0
        ram_avail_gb = 0.0
        battery_pct = None

        if psutil:
            try:
                cpu = psutil.cpu_percent(interval=0.05)
                vm = psutil.virtual_memory()
                ram_pct = round(vm.percent, 1)
                ram_avail_gb = round(vm.available / (1024 ** 3), 2)
                battery = psutil.sensors_battery()
                if battery:
                    battery_pct = round(battery.percent, 1)
            except Exception as e:
                logger.warning(f"Error reading psutil metrics: {e}")

        # Active foreground window title
        active_window = ""
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
        """Execute a shell or terminal command."""
        try:
            res = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return {
                "success": res.returncode == 0,
                "command": command,
                "exit_code": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "message": f"Command exited with code {res.returncode}"
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "command": command, "error": f"Command timed out after {timeout}s"}
        except Exception as exc:
            return {"success": False, "command": command, "error": str(exc)}
