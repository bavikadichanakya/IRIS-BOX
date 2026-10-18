from __future__ import annotations
import os
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("iris.operator.app_launcher")


class AppLauncher:
    """
    Application Discovery and Clean Launch Registry for Windows Desktop:
    - Scans Start Menu folders, registry App Paths, and standard system binaries.
    - Resolves natural language aliases (e.g. 'browser' -> Chrome/Edge, 'code' -> VS Code).
    - Asynchronously spawns applications cleanly detached from the assistant runtime.
    """

    # Pre-configured core developer tools and system utilities
    KNOWN_APPS: Dict[str, str] = {
        "notepad": "notepad.exe",
        "calc": "calc.exe",
        "calculator": "calc.exe",
        "explorer": "explorer.exe",
        "files": "explorer.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "powershell": "powershell.exe",
        "wt": "wt.exe",
        "terminal": "wt.exe",
        "windows terminal": "wt.exe",
        "code": "code",
        "vscode": "code",
        "vs code": "code",
        "visual studio code": "code",
        "cursor": "cursor",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "browser": "chrome.exe",
        "edge": "msedge.exe",
        "msedge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "spotify": "spotify.exe",
        "antigravity": "Antigravity.exe",
        "antigravity ide": "Antigravity IDE.exe",
    }

    _cached_apps: Optional[Dict[str, str]] = None

    @classmethod
    def list_known_apps(cls, force_refresh: bool = False) -> Dict[str, str]:
        """
        Discover installed applications by scanning Start Menu shortcuts and Windows registry App Paths.
        Results are cached in memory for high-performance lookup.
        """
        if cls._cached_apps is not None and not force_refresh:
            return cls._cached_apps

        apps: Dict[str, str] = dict(cls.KNOWN_APPS)

        # 1. Query Windows Registry App Paths
        if os.name == "nt":
            try:
                import winreg
                for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(
                            root_key,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
                        ) as key:
                            num_subkeys = winreg.QueryInfoKey(key)[0]
                            for i in range(num_subkeys):
                                try:
                                    subkey_name = winreg.EnumKey(key, i)
                                    with winreg.OpenKey(key, subkey_name) as subkey:
                                        val, _ = winreg.QueryValueEx(subkey, "")
                                        if val:
                                            expanded_val = os.path.expandvars(val)
                                            norm_name = subkey_name.lower().removesuffix(".exe")
                                            apps[norm_name] = expanded_val
                                            apps[subkey_name.lower()] = expanded_val
                                except Exception:
                                    continue
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Registry App Paths lookup skipped: {e}")

        # 2. Scan Start Menu Folders for .lnk shortcuts
        start_menu_dirs: List[Path] = []
        if os.name == "nt":
            prog_data = os.environ.get("ProgramData", "C:/ProgramData")
            app_data = os.environ.get("APPDATA", "")
            start_menu_dirs.extend([
                Path(prog_data) / "Microsoft/Windows/Start Menu/Programs",
                Path(app_data) / "Microsoft/Windows/Start Menu/Programs",
            ])

        for sdir in start_menu_dirs:
            if sdir.exists() and sdir.is_dir():
                try:
                    for lnk in sdir.rglob("*.lnk"):
                        name = lnk.stem.lower()
                        # Avoid overriding explicitly registered high-priority binaries
                        if name not in apps:
                            apps[name] = str(lnk.resolve())
                except Exception as e:
                    logger.debug(f"Error scanning Start Menu in '{sdir}': {e}")

        cls._cached_apps = apps
        logger.info(f"Discovered {len(apps)} installed applications and shortcuts.")
        return apps

    @classmethod
    def find_app(cls, app_name: str) -> Optional[str]:
        """
        Locate application executable or shortcut by name, alias, or fuzzy substring.
        """
        if not app_name or not app_name.strip():
            return None

        clean_name = app_name.lower().strip()
        all_apps = cls.list_known_apps()

        # 1. Exact match in registry/shortcuts
        if clean_name in all_apps:
            return all_apps[clean_name]

        # 2. Standard aliases fallback
        alias_target = cls.KNOWN_APPS.get(clean_name)
        if alias_target:
            resolved_alias = shutil.which(alias_target) or all_apps.get(alias_target.lower())
            if resolved_alias:
                return resolved_alias
            return alias_target

        # 3. Substring match (e.g. 'chrome' matches 'google chrome')
        for name, path in all_apps.items():
            if clean_name == name or clean_name in name:
                return path

        # 4. Check if available on system PATH
        which_path = shutil.which(clean_name) or shutil.which(f"{clean_name}.exe")
        if which_path:
            return which_path

        # 5. Word match (e.g. 'visual studio code' -> 'code')
        for word in clean_name.split():
            if len(word) > 2 and word in all_apps:
                return all_apps[word]

        return None

    @classmethod
    def launch_app(cls, app_name: str) -> Dict[str, Any]:
        """
        Launch target application cleanly detached from current Python process.
        Returns dictionary containing launch status, path, and PID.
        """
        target = cls.find_app(app_name)
        if not target:
            raise FileNotFoundError(f"Could not find application matching '{app_name}'.")

        logger.info(f"Launching application '{app_name}' from target: {target}")

        if os.name == "nt":
            # If target is a shortcut (.lnk) or URL
            if target.lower().endswith((".lnk", ".url")):
                try:
                    os.startfile(target)
                    return {
                        "app_name": app_name,
                        "binary_path": target,
                        "pid": None,
                        "status": "LAUNCHED",
                    }
                except Exception as exc:
                    logger.debug(f"os.startfile failed for '{target}': {exc}, falling back to cmd start")
                    cmd = ["cmd.exe", "/c", "start", "", target]
                    subprocess.Popen(
                        cmd,
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                        close_fds=True,
                    )
                    return {
                        "app_name": app_name,
                        "binary_path": target,
                        "pid": None,
                        "status": "LAUNCHED",
                    }

            # If executable binary
            resolved_bin = os.path.expandvars(target)
            creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                proc = subprocess.Popen(
                    [resolved_bin],
                    creationflags=creation_flags,
                    close_fds=True,
                    shell=False,
                )
                return {
                    "app_name": app_name,
                    "binary_path": resolved_bin,
                    "pid": proc.pid,
                    "status": "LAUNCHED",
                }
            except Exception as e:
                # Fallback to os.startfile if direct execution fails
                try:
                    os.startfile(resolved_bin)
                    return {
                        "app_name": app_name,
                        "binary_path": resolved_bin,
                        "pid": None,
                        "status": "LAUNCHED",
                    }
                except Exception:
                    raise RuntimeError(f"Failed to launch '{app_name}' ({resolved_bin}): {e}")

        else:
            # Linux / macOS fallback
            proc = subprocess.Popen(
                [target],
                start_new_session=True,
                close_fds=True,
            )
            return {
                "app_name": app_name,
                "binary_path": target,
                "pid": proc.pid,
                "status": "LAUNCHED",
            }
