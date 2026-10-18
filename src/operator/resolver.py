import difflib
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("iris.operator.resolver")

GENERIC_PROJECT_REFERENCES: Set[str] = {
    "my project",
    "this project",
    "the project",
    "here",
    "current project",
    "my current project",
    "current workspace",
    "this workspace",
    "the workspace",
    "project",
    "workspace",
    "here project",
}


def extract_reference_from_utterance(utterance: str) -> str:
    """
    Extract target project name or reference from natural spoken utterance.
    Strips wake words, greetings, and common intent prefixes.
    """
    if not utterance:
        return ""
    s = utterance.strip().rstrip(".!?")
    # Strip wake phrases
    s = re.sub(r"^(hey\s+iris|iris|okay\s+iris|ok\s+iris)[,\s]*", "", s, flags=re.IGNORECASE).strip()
    # Strip common operator query prefixes
    patterns = [
        r"^(please\s+)?(check|diagnose|see|tell\s+me)\s+(why\s+)?tests?\s+(are\s+)?failing\s+in\s+",
        r"^(please\s+)?(check|inspect|diagnose|test|fix|run\s+tests?\s+(in|on|for)?)\s+",
        r"^(what|why)\s+(is|are)\s+failing\s+in\s+",
    ]
    for pat in patterns:
        s = re.sub(pat, "", s, flags=re.IGNORECASE).strip()
    return s


def parse_window_title(title: str) -> Optional[str]:
    """
    Extract project or folder name from active editor and terminal window titles.
    Supports VS Code, Cursor, PyCharm, IntelliJ IDEA, and Windows Terminal.
    """
    if not title or not title.strip():
        return None

    clean_title = title.strip().lstrip("● ").strip()

    # 1. VS Code and Cursor: e.g. "file.py - project-name - Visual Studio Code"
    for ide in ("Visual Studio Code", "Cursor", "VSCodium"):
        if ide in clean_title:
            prefix = clean_title.split(f" - {ide}")[0]
            parts = prefix.split(" - ")
            if parts:
                candidate = parts[-1].strip()
                if candidate.endswith(" (Workspace)"):
                    candidate = candidate[:-12].strip()
                if candidate:
                    return candidate

    # 2. Windows Terminal: e.g. "project-name - Windows Terminal" or "Windows PowerShell - project-name"
    if " - Windows Terminal" in clean_title:
        candidate = clean_title.split(" - Windows Terminal")[0].strip()
        if " - " in candidate:
            candidate = candidate.split(" - ")[-1].strip()
        if candidate:
            return candidate

    if clean_title.startswith("Windows PowerShell - "):
        return clean_title.replace("Windows PowerShell - ", "").strip()

    # 3. PyCharm / IntelliJ: e.g. "project-name – file.py" or "project-name [C:\...] - file.py"
    for dash in (" \u2013 ", " \u2014 ", " - "):
        if dash in clean_title:
            candidate = clean_title.split(dash)[0].strip()
            if " [" in candidate and "]" in candidate:
                candidate = candidate.split(" [")[0].strip()
            if candidate and not any(ext in candidate.lower() for ext in (".py", ".js", ".ts", ".html", ".css", ".md", ".json")):
                return candidate

    if " [" in clean_title and "]" in clean_title:
        candidate = clean_title.split(" [")[0].strip()
        if candidate:
            return candidate

    # 4. General fallback: if " - " exists, grab candidate
    if " - " in clean_title:
        parts = clean_title.split(" - ")
        return parts[0].strip()

    return clean_title


class WorkspaceResolver:
    """
    Smart Workspace Resolution Engine:
    - Resolves spoken project references without requiring absolute Windows paths.
    - Inspects foreground/running IDEs (VS Code, Cursor, Windows Terminal, PyCharm).
    - Fuzzy matches project names against configurable WORKSPACE_ROOTS.
    - Maintains session recency for generic references like 'my project' or 'here'.
    """

    def __init__(
        self,
        workspace_roots: Optional[List[str]] = None,
        last_active_project_path: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        active_window_getter: Optional[Any] = None,
    ):
        self.workspace_roots: List[str] = workspace_roots or self._default_workspace_roots()
        self.last_active_project_path: Optional[str] = last_active_project_path
        self.session_state: Dict[str, Any] = session_state or {}
        self.active_window_getter: Optional[Any] = active_window_getter

    @staticmethod
    def _default_workspace_roots() -> List[str]:
        """Construct standard project search roots from environment and user directory."""
        roots: List[str] = []
        env_roots = os.getenv("IRIS_WORKSPACE_ROOTS")
        if env_roots:
            for r in env_roots.split(","):
                r_clean = r.strip()
                if r_clean and os.path.isdir(r_clean):
                    roots.append(str(Path(r_clean).resolve()))

        user_home = Path.home()
        candidates = [
            user_home / "projects",
            user_home / "Projects",
            user_home / "workspace",
            user_home / "dev",
            user_home,
            Path.cwd(),
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                resolved = str(c.resolve())
                if resolved not in roots:
                    roots.append(resolved)

        return roots

    def set_active_project(self, path: str):
        """Update last active workspace recency."""
        if path and os.path.isdir(path):
            self.last_active_project_path = str(Path(path).resolve())
            self.session_state["last_project_path"] = self.last_active_project_path

    def get_foreground_window_title(self) -> Optional[str]:
        """Inspect the current foreground active window title on Windows."""
        if os.name != "nt":
            return None
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                return buff.value
        except Exception as e:
            logger.debug(f"Foreground window inspection failed: {e}")
        return None

    def get_running_ide_window_titles(self) -> List[str]:
        """Query main window titles of running IDEs and Terminals via PowerShell."""
        if os.name != "nt":
            return []
        try:
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-Process Code, Cursor, WindowsTerminal, pycharm64, pycharm, idea64 -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle } | Select-Object -ExpandProperty MainWindowTitle"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.5)
            if res.returncode == 0 and res.stdout.strip():
                return [line.strip() for line in res.stdout.splitlines() if line.strip()]
        except Exception as e:
            logger.debug(f"Running IDE query failed: {e}")
        return []

    def inspect_active_editor_project(self) -> Optional[str]:
        """
        Check foreground window or running IDEs to extract active project folder.
        """
        # 0. Custom active window getter (for testing / mocking)
        if self.active_window_getter:
            try:
                custom_title = self.active_window_getter()
                if custom_title:
                    proj_candidate = parse_window_title(custom_title)
                    if proj_candidate:
                        matched = self._match_candidate_in_roots(proj_candidate)
                        if matched:
                            return matched
                        if os.path.isdir(proj_candidate):
                            return str(Path(proj_candidate).resolve())
            except Exception as e:
                logger.debug(f"Custom active window inspection failed: {e}")

        # 1. Foreground window
        fg_title = self.get_foreground_window_title()
        if fg_title:
            proj_candidate = parse_window_title(fg_title)
            if proj_candidate:
                resolved = self._match_candidate_in_roots(proj_candidate)
                if resolved:
                    return resolved

        # 2. Running IDE windows
        titles = self.get_running_ide_window_titles()
        for t in titles:
            proj_candidate = parse_window_title(t)
            if proj_candidate:
                resolved = self._match_candidate_in_roots(proj_candidate)
                if resolved:
                    return resolved

        return None

    def _normalize_name(self, name: str) -> str:
        """Normalize project name for comparisons (alphanumeric + single spaces)."""
        s = name.lower().replace("-", " ").replace("_", " ")
        s = re.sub(r"[^a-z0-9\s]", "", s)
        return " ".join(s.split())

    def _collect_root_directories(self) -> Dict[str, Path]:
        """
        Scans directories under configured workspace roots.
        Returns a mapping of normalized_name -> Path.
        """
        dir_map: Dict[str, Path] = {}

        ignore_dirs = {
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            "AppData", "Local Settings", "Application Data",
        }

        for root_str in self.workspace_roots:
            root_p = Path(root_str)
            if not root_p.exists() or not root_p.is_dir():
                continue

            # Check root itself if it's a project (e.g. current working directory)
            norm_root = self._normalize_name(root_p.name)
            if norm_root and norm_root not in dir_map:
                dir_map[norm_root] = root_p

            # Immediate subdirectories
            try:
                for entry in root_p.iterdir():
                    if entry.is_dir() and entry.name not in ignore_dirs and not entry.name.startswith("."):
                        norm_entry = self._normalize_name(entry.name)
                        if norm_entry and norm_entry not in dir_map:
                            dir_map[norm_entry] = entry

                        # Check 1 level deeper if entry is a "projects" folder
                        if entry.name.lower() in ("projects", "workspace", "dev", "repos"):
                            try:
                                for sub in entry.iterdir():
                                    if sub.is_dir() and sub.name not in ignore_dirs and not sub.name.startswith("."):
                                        norm_sub = self._normalize_name(sub.name)
                                        if norm_sub and norm_sub not in dir_map:
                                            dir_map[norm_sub] = sub
                            except Exception:
                                pass
            except Exception as e:
                logger.debug(f"Error scanning workspace root '{root_str}': {e}")

        return dir_map

    def _match_candidate_in_roots(self, candidate_name: str) -> Optional[str]:
        """Attempts exact or high-confidence match for candidate name inside workspace roots."""
        if not candidate_name:
            return None

        dir_map = self._collect_root_directories()
        norm_candidate = self._normalize_name(candidate_name)

        # 1. Exact normalized match
        if norm_candidate in dir_map:
            return str(dir_map[norm_candidate].resolve())

        # 2. Substring or sub-slug match
        for norm_name, path in dir_map.items():
            if norm_candidate == norm_name:
                return str(path.resolve())
            if norm_candidate in norm_name or norm_name in norm_candidate:
                return str(path.resolve())

        # 3. Fuzzy close matches
        matches = difflib.get_close_matches(norm_candidate, list(dir_map.keys()), n=1, cutoff=0.7)
        if matches:
            return str(dir_map[matches[0]].resolve())

        return None

    def resolve_project_path(
        self,
        spoken_reference: Optional[str] = None,
        custom_roots: Optional[List[str]] = None,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Main entry point for smart workspace resolution:
        1. Direct path match if a valid filesystem directory was supplied.
        2. Recency / active window fallback if reference is generic or omitted.
        3. Active window inspection if editor title reveals active repository.
        4. Fuzzy directory search across configured WORKSPACE_ROOTS.
        5. Returns None if completely ambiguous.
        """
        if custom_roots:
            self.workspace_roots = custom_roots

        active_state = session_state if session_state is not None else self.session_state
        clean_ref = spoken_reference.strip() if spoken_reference else ""

        # 1. Direct path match
        if clean_ref:
            direct_path = Path(clean_ref)
            if direct_path.exists() and direct_path.is_dir():
                resolved = str(direct_path.resolve())
                self.set_active_project(resolved)
                logger.info(f"Resolved direct project path: {resolved}")
                return resolved

            extracted = extract_reference_from_utterance(clean_ref)
            if extracted:
                clean_ref = extracted

        # 2. Generic / Empty reference -> Recency or Active Window Fallback
        is_generic = (not clean_ref) or (clean_ref.lower() in GENERIC_PROJECT_REFERENCES)
        if is_generic:
            recency = None
            if active_state and isinstance(active_state, dict):
                recency = active_state.get("last_project_path") or active_state.get("last_active_project_path")
            if not recency:
                recency = self.last_active_project_path

            # If user explicitly said "this project", "my project", "here", check recency first
            if clean_ref and clean_ref.lower() in GENERIC_PROJECT_REFERENCES and recency and os.path.isdir(recency):
                logger.info(f"Resolved generic reference '{clean_ref}' from recency: {recency}")
                return str(Path(recency).resolve())

            # Active IDE window inspection
            active_from_window = self.inspect_active_editor_project()
            if active_from_window:
                self.set_active_project(active_from_window)
                logger.info(f"Resolved project from active IDE window: {active_from_window}")
                return active_from_window

            # Next check session recency if reference was omitted
            if recency and os.path.isdir(recency):
                logger.info(f"Resolved project from session recency: {recency}")
                return str(Path(recency).resolve())

            # Fallback to current working directory if valid repository
            cwd_str = str(Path.cwd().resolve())
            if os.path.isdir(cwd_str):
                self.set_active_project(cwd_str)
                logger.info(f"Defaulting to current working directory: {cwd_str}")
                return cwd_str

            return None

        # 3. Named Project Search via Fuzzy Directory Matching
        dir_map = self._collect_root_directories()
        norm_ref = self._normalize_name(clean_ref)

        # 3a. Exact normalized match
        if norm_ref in dir_map:
            resolved = str(dir_map[norm_ref].resolve())
            self.set_active_project(resolved)
            logger.info(f"Exact normalized match resolved '{clean_ref}' -> {resolved}")
            return resolved

        # 3b. Exact raw folder name match
        for _, path in dir_map.items():
            if path.name.lower() == clean_ref.lower():
                resolved = str(path.resolve())
                self.set_active_project(resolved)
                logger.info(f"Raw name match resolved '{clean_ref}' -> {resolved}")
                return resolved

        # 3c. Substring matching
        matching_paths: List[Path] = []
        for norm_name, path in dir_map.items():
            if norm_ref in norm_name or norm_name in norm_ref:
                matching_paths.append(path)

        if matching_paths:
            # Pick shortest name (closest match)
            best_match = min(matching_paths, key=lambda p: abs(len(p.name) - len(clean_ref)))
            resolved = str(best_match.resolve())
            self.set_active_project(resolved)
            logger.info(f"Substring match resolved '{clean_ref}' -> {resolved}")
            return resolved

        # 3d. Fuzzy close match
        candidates = list(dir_map.keys())
        matches = difflib.get_close_matches(norm_ref, candidates, n=1, cutoff=0.55)
        if matches:
            resolved = str(dir_map[matches[0]].resolve())
            self.set_active_project(resolved)
            logger.info(f"Fuzzy match resolved '{clean_ref}' -> {resolved}")
            return resolved

        # 4. Active IDE Window Title Fallback for the spoken reference
        active_from_window = self.inspect_active_editor_project()
        if active_from_window:
            proj_name = Path(active_from_window).name
            if norm_ref in self._normalize_name(proj_name):
                self.set_active_project(active_from_window)
                return active_from_window

        logger.warning(f"Unable to resolve project path for reference '{spoken_reference}'")
        return None
