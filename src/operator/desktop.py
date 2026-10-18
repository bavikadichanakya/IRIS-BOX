from __future__ import annotations
import os
import sys
import time
import logging
from typing import Any, Dict, List, Optional, Set

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger("iris.operator.desktop")


class DesktopEnvironment:
    """
    Desktop Environment & Process Intelligence Subsystem for IRIS AI Computer Operator:
    - System health & telemetry (CPU, RAM, Disk, Battery).
    - Resource bottleneck inspector (top processes sorted by CPU or memory).
    - Service daemon watchdog (Docker, Ollama, WSL, Postgres, Redis, etc.).
    - Desktop visible window enumeration and foreground window tracking.
    - Safe process termination with strict system process blacklist protection.
    """

    # Protected core OS binaries and critical background services that must never be killed
    PROTECTED_SYSTEM_PROCESSES: Set[str] = {
        "system",
        "system idle process",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "svchost.exe",
        "dwm.exe",
        "explorer.exe",
        "winlogon.exe",
        "runtimebroker.exe",
        "securityhealthservice.exe",
        "antigravity.exe",
        "antigravity ide.exe",
        # Common Linux / Unix core daemons
        "init",
        "systemd",
        "launchd",
        "kernel_task",
    }

    # Known developer daemons and their process name substrings
    KNOWN_SERVICES: Dict[str, List[str]] = {
        "docker": ["docker.exe", "dockerd", "docker desktop.exe", "com.docker.backend.exe"],
        "ollama": ["ollama.exe", "ollama app.exe", "ollama"],
        "wsl": ["wslservice.exe", "wsl.exe", "wslhost.exe"],
        "postgres": ["postgres.exe", "postgresql.exe", "postgres"],
        "redis": ["redis-server.exe", "redis-server", "memurai.exe"],
        "code": ["code.exe", "code"],
        "cursor": ["cursor.exe", "cursor"],
    }

    @staticmethod
    def get_system_metrics() -> Dict[str, Any]:
        """
        Extract instantaneous system telemetry:
        CPU usage percent, memory utilization (GB and percent), disk usage (GB and percent),
        and battery state.
        """
        if psutil is None:
            return {
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "total_ram_gb": 0.0,
                "available_ram_gb": 0.0,
                "used_ram_gb": 0.0,
                "disk_total_gb": 0.0,
                "disk_used_gb": 0.0,
                "disk_free_gb": 0.0,
                "disk_percent": 0.0,
                "battery_percent": None,
                "power_plugged": True,
                "battery_secsleft": None,
            }

        # CPU percent (non-blocking call)
        cpu_pct = psutil.cpu_percent(interval=None)
        if cpu_pct == 0.0:
            cpu_pct = psutil.cpu_percent(interval=0.05)

        # Virtual Memory
        vm = psutil.virtual_memory()
        mem_pct = round(vm.percent, 1)
        total_ram = round(vm.total / (1024 ** 3), 2)
        avail_ram = round(vm.available / (1024 ** 3), 2)
        used_ram = round(vm.used / (1024 ** 3), 2)

        # Disk Capacity (root directory or workspace drive)
        try:
            root_drive = os.path.splitdrive(os.getcwd())[0] + os.sep if os.name == "nt" else os.sep
            disk = psutil.disk_usage(root_drive)
            disk_total = round(disk.total / (1024 ** 3), 2)
            disk_used = round(disk.used / (1024 ** 3), 2)
            disk_free = round(disk.free / (1024 ** 3), 2)
            disk_pct = round(disk.percent, 1)
        except Exception as e:
            logger.debug(f"Failed to read disk capacity: {e}")
            disk_total, disk_used, disk_free, disk_pct = 0.0, 0.0, 0.0, 0.0

        # Battery telemetry
        batt_pct = None
        plugged = True
        secsleft = None
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                batt_pct = battery.percent
                plugged = battery.power_plugged
                secsleft = battery.secsleft if battery.secsleft != -2 else None
        except Exception as e:
            logger.debug(f"Failed to read battery status: {e}")

        return {
            "cpu_percent": round(cpu_pct, 1),
            "memory_percent": mem_pct,
            "total_ram_gb": total_ram,
            "available_ram_gb": avail_ram,
            "used_ram_gb": used_ram,
            "disk_total_gb": disk_total,
            "disk_used_gb": disk_used,
            "disk_free_gb": disk_free,
            "disk_percent": disk_pct,
            "battery_percent": batt_pct,
            "power_plugged": plugged,
            "battery_secsleft": secsleft,
        }

    @staticmethod
    def get_top_processes(limit: int = 5, sort_by: str = "cpu") -> List[Dict[str, Any]]:
        """
        Enumerate and sort active processes by CPU or memory usage.
        Returns top `limit` processes with PID, name, CPU %, memory MB, and status.
        """
        if psutil is None:
            return []

        sort_by_lower = (sort_by or "cpu").lower()
        procs: List[Dict[str, Any]] = []

        for p in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_info", "memory_percent", "status"]
        ):
            try:
                info = p.info
                pid = info.get("pid")
                name = info.get("name") or "unknown"
                mem_info = info.get("memory_info")
                mem_bytes = mem_info.rss if mem_info else 0
                mem_mb = round(mem_bytes / (1024 ** 2), 1)
                mem_pct = round(info.get("memory_percent") or 0.0, 1)
                cpu_pct = round(info.get("cpu_percent") or 0.0, 1)
                status = info.get("status") or "running"

                procs.append({
                    "pid": pid,
                    "name": name,
                    "cpu_percent": cpu_pct,
                    "memory_mb": mem_mb,
                    "memory_percent": mem_pct,
                    "status": str(status),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if sort_by_lower in ("memory", "mem", "ram"):
            procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        else:
            procs.sort(key=lambda x: x["cpu_percent"], reverse=True)

        return procs[: max(1, limit)]

    @classmethod
    def inspect_service(cls, service_name: str) -> Dict[str, Any]:
        """
        Check if a given developer daemon or background service is running.
        Supports fuzzy name lookup for 'docker', 'ollama', 'wsl', 'postgres', 'redis', 'code', 'cursor'.
        """
        sname = service_name.lower().strip()
        patterns = cls.KNOWN_SERVICES.get(sname, [sname, f"{sname}.exe"])

        if psutil is None:
            return {
                "service_name": service_name,
                "running": False,
                "pid": None,
                "process_name": None,
                "uptime_seconds": None,
                "memory_mb": None,
                "cpu_percent": None,
                "status": "stopped",
            }

        matched_proc = None
        for p in psutil.process_iter(["pid", "name", "create_time", "status", "memory_info"]):
            try:
                pname = (p.info.get("name") or "").lower()
                if any(pat in pname for pat in patterns):
                    matched_proc = p
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if matched_proc:
            try:
                uptime = round(time.time() - matched_proc.info.get("create_time", time.time()), 1)
                mem_info = matched_proc.info.get("memory_info")
                mem_mb = round((mem_info.rss if mem_info else 0) / (1024 ** 2), 1)
                return {
                    "service_name": service_name,
                    "running": True,
                    "pid": matched_proc.pid,
                    "process_name": matched_proc.name(),
                    "uptime_seconds": uptime,
                    "memory_mb": mem_mb,
                    "cpu_percent": round(matched_proc.cpu_percent(interval=None), 1),
                    "status": matched_proc.status(),
                }
            except Exception as e:
                logger.debug(f"Error inspecting matched process: {e}")

        return {
            "service_name": service_name,
            "running": False,
            "pid": None,
            "process_name": None,
            "uptime_seconds": None,
            "memory_mb": None,
            "cpu_percent": None,
            "status": "stopped",
        }

    @classmethod
    def inspect_common_services(cls) -> Dict[str, Dict[str, Any]]:
        """
        Inspect standard local development daemons: Docker, Ollama, WSL, Postgres, Redis.
        """
        common = ["docker", "ollama", "wsl", "postgres", "redis"]
        return {svc: cls.inspect_service(svc) for svc in common}

    @staticmethod
    def get_listening_ports(limit: int = 50) -> List[Dict[str, Any]]:
        """
        Enumerate local TCP listening ports and their associated processes.
        """
        if psutil is None:
            return []

        listening_ports: List[Dict[str, Any]] = []
        try:
            conns = psutil.net_connections(kind="tcp")
            for c in conns:
                if c.status == psutil.CONN_LISTEN and c.laddr:
                    pname = "unknown"
                    if c.pid:
                        try:
                            pname = psutil.Process(c.pid).name()
                        except Exception:
                            pass
                    listening_ports.append({
                        "port": c.laddr.port,
                        "ip": c.laddr.ip,
                        "pid": c.pid,
                        "process_name": pname,
                    })
        except Exception as e:
            logger.debug(f"Failed to inspect listening ports: {e}")

        # Deduplicate by port
        unique_ports = {}
        for entry in listening_ports:
            port = entry["port"]
            if port not in unique_ports:
                unique_ports[port] = entry

        res = list(unique_ports.values())
        res.sort(key=lambda x: x["port"])
        return res[:limit]

    @staticmethod
    def get_visible_windows() -> List[Dict[str, Any]]:
        """
        Enumerate all visible desktop application windows with their titles, HWNDs,
        and owning processes.
        Uses interactive desktop handle on Windows to ensure visibility even from
        background subshells.
        """
        windows: List[Dict[str, Any]] = []

        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32

                WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

                def enum_cb(hwnd, lparam):
                    if user32.IsWindowVisible(hwnd):
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buff, length + 1)
                            title = buff.value.strip()
                            if title:
                                pid = wintypes.DWORD()
                                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                                pname = "unknown"
                                if psutil and pid.value:
                                    try:
                                        pname = psutil.Process(pid.value).name()
                                    except Exception:
                                        pass
                                windows.append({
                                    "hwnd": hwnd,
                                    "title": title,
                                    "pid": pid.value,
                                    "process_name": pname,
                                })
                    return True

                cb = WNDENUMPROC(enum_cb)
                # Attempt to open the interactive user desktop 'Default'
                hdesk = user32.OpenDesktopW("Default", 0, False, 0x0100)
                if hdesk:
                    try:
                        user32.EnumDesktopWindows(hdesk, cb, 0)
                    finally:
                        user32.CloseDesktop(hdesk)
                else:
                    user32.EnumWindows(cb, 0)

            except Exception as e:
                logger.debug(f"Window enumeration failed: {e}")
        else:
            logger.debug("Window enumeration is only supported natively on Windows.")

        return windows

    @staticmethod
    def get_focused_window() -> Optional[Dict[str, Any]]:
        """
        Get details of the currently focused foreground application window.
        """
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32

                hwnd = user32.GetForegroundWindow()
                if not hwnd:
                    return None
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.strip()

                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pname = "unknown"
                if psutil and pid.value:
                    try:
                        pname = psutil.Process(pid.value).name()
                    except Exception:
                        pass

                return {
                    "hwnd": hwnd,
                    "title": title,
                    "pid": pid.value,
                    "process_name": pname,
                }
            except Exception as e:
                logger.debug(f"Failed to get focused window: {e}")
        return None

    @staticmethod
    def focus_window(hwnd: int) -> bool:
        """
        Brings the specified window handle to the foreground and restores it.
        """
        if os.name == "nt":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                # SW_RESTORE = 9
                user32.ShowWindow(hwnd, 9)
                return bool(user32.SetForegroundWindow(hwnd))
            except Exception as e:
                logger.warning(f"Failed to focus window {hwnd}: {e}")
        return False

    @classmethod
    def kill_process(cls, pid: int) -> bool:
        """
        Safely terminates a process by PID.
        Guarantees that protected core OS processes (System, csrss, svchost, explorer, PID 0, PID 4,
        and the running assistant process itself) are never terminated.
        Raises PermissionError if a protected target is selected.
        """
        if pid <= 4:
            raise PermissionError(
                f"SECURITY_DENIED: PID {pid} is a protected core system process and cannot be terminated."
            )

        current_pid = os.getpid()
        if pid == current_pid:
            raise PermissionError(
                f"SECURITY_DENIED: Cannot terminate the active IRIS runtime process (PID {pid})."
            )

        if psutil is None:
            raise RuntimeError("psutil is not installed.")

        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            raise ProcessLookupError(f"Process with PID {pid} does not exist.")

        name = proc.name().lower()
        base_name = name.removesuffix(".exe")

        if name in cls.PROTECTED_SYSTEM_PROCESSES or base_name in cls.PROTECTED_SYSTEM_PROCESSES:
            raise PermissionError(
                f"SECURITY_DENIED: Process '{name}' (PID {pid}) is protected by system security policy."
            )

        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
            logger.info(f"Terminated process '{name}' (PID {pid}) successfully.")
            return True
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return True
        except psutil.AccessDenied as e:
            raise PermissionError(f"Access denied terminating PID {pid} ('{name}'): {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to terminate PID {pid}: {e}")
