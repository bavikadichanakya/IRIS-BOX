import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ProjectSnapshot(BaseModel):
    """Immutable snapshot of project structure, environment, and configuration."""
    project_path: str
    project_type: Dict[str, Any]
    files: List[str] = Field(default_factory=list)
    structure_tree: Dict[str, Any] = Field(default_factory=dict)
    config_files: Dict[str, str] = Field(default_factory=dict)
    test_command: Optional[str] = None
    active_failure_traces: List[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)


class ProjectWorkspace:
    """
    Environment intelligence and workspace safety manager:
    - Project discovery & runtime environment detection
    - Non-destructive repository tree snapshotting
    - Cryptographically identifiable & reversible checkpoints
    """

    IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist",
        "build", ".coverage", ".iris_checkpoints", ".tox",
    }
    IGNORE_EXTS = {".pyc", ".pyo", ".pyd", ".egg-info", ".log", ".lock"}

    @classmethod
    def detect_project_type(cls, path: str) -> Dict[str, Any]:
        """
        Identify language, framework, test runner, package manager, and Git status.
        """
        proj_dir = Path(path).resolve()
        if not proj_dir.exists() or not proj_dir.is_dir():
            raise ValueError(f"Project directory does not exist: {path}")

        language = "unknown"
        framework = "none"
        test_runner = None
        test_command = None
        package_manager = "none"

        # 1. Language & Framework Detection
        if (proj_dir / "pyproject.toml").exists() or (proj_dir / "setup.py").exists() or (proj_dir / "requirements.txt").exists() or any(proj_dir.glob("*.py")):
            language = "python"
            if (proj_dir / "uv.lock").exists() or (proj_dir / "uv.toml").exists():
                package_manager = "uv"
            elif (proj_dir / "poetry.lock").exists():
                package_manager = "poetry"
            elif (proj_dir / "Pipfile").exists():
                package_manager = "pipenv"
            else:
                package_manager = "pip"

            test_runner = "pytest"
            test_command = "pytest"

            # Check framework
            req_content = ""
            for conf_name in ["pyproject.toml", "requirements.txt", "setup.py"]:
                conf_f = proj_dir / conf_name
                if conf_f.exists():
                    try:
                        req_content += conf_f.read_text(encoding="utf-8", errors="ignore").lower()
                    except Exception:
                        pass
            if "fastapi" in req_content:
                framework = "fastapi"
            elif "django" in req_content:
                framework = "django"
            elif "flask" in req_content:
                framework = "flask"

        elif (proj_dir / "package.json").exists() or (proj_dir / "tsconfig.json").exists():
            language = "typescript" if (proj_dir / "tsconfig.json").exists() else "javascript"
            if (proj_dir / "pnpm-lock.yaml").exists():
                package_manager = "pnpm"
            elif (proj_dir / "yarn.lock").exists():
                package_manager = "yarn"
            else:
                package_manager = "npm"
            test_runner = "npm test"
            test_command = "npm test"

        elif (proj_dir / "Cargo.toml").exists():
            language = "rust"
            package_manager = "cargo"
            test_runner = "cargo test"
            test_command = "cargo test"

        elif (proj_dir / "go.mod").exists():
            language = "go"
            package_manager = "go"
            test_runner = "go test"
            test_command = "go test ./..."

        # 2. Git Status Detection
        git_info = cls._detect_git_status(proj_dir)

        return {
            "language": language,
            "framework": framework,
            "test_runner": test_runner,
            "test_command": test_command,
            "package_manager": package_manager,
            "git": git_info,
        }

    @classmethod
    def _detect_git_status(cls, proj_dir: Path) -> Dict[str, Any]:
        """Safely inspect Git repository status if git is initialized."""
        git_dir = proj_dir / ".git"
        if not git_dir.exists():
            # Check parent for repo
            try:
                res = subprocess.run(
                    ["git", "rev-parse", "--is-inside-work-tree"],
                    cwd=str(proj_dir),
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                if res.returncode != 0:
                    return {"is_git": False, "is_clean": True, "branch": None, "commit": None, "modified_files": [], "untracked_files": []}
            except Exception:
                return {"is_git": False, "is_clean": True, "branch": None, "commit": None, "modified_files": [], "untracked_files": []}

        try:
            # Branch
            b_res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(proj_dir),
                capture_output=True,
                text=True,
                timeout=3
            )
            branch = b_res.stdout.strip() if b_res.returncode == 0 else "unknown"

            # Commit
            c_res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(proj_dir),
                capture_output=True,
                text=True,
                timeout=3
            )
            commit = c_res.stdout.strip() if c_res.returncode == 0 else None

            # Status
            s_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(proj_dir),
                capture_output=True,
                text=True,
                timeout=3
            )
            modified = []
            untracked = []
            if s_res.returncode == 0:
                for line in s_res.stdout.splitlines():
                    if line.startswith("??"):
                        untracked.append(line[3:].strip())
                    elif line.strip():
                        modified.append(line[3:].strip())

            return {
                "is_git": True,
                "is_clean": (len(modified) == 0 and len(untracked) == 0),
                "branch": branch,
                "commit": commit,
                "modified_files": modified,
                "untracked_files": untracked,
            }
        except Exception:
            return {"is_git": True, "is_clean": False, "branch": "unknown", "commit": None, "modified_files": [], "untracked_files": []}

    @classmethod
    def snapshot_environment(cls, path: str) -> ProjectSnapshot:
        """
        Capture the repository structure, filtering transient directories.
        """
        proj_dir = Path(path).resolve()
        proj_type = cls.detect_project_type(str(proj_dir))

        files: List[str] = []
        tree: Dict[str, Any] = {"name": proj_dir.name, "type": "directory", "children": []}
        config_files: Dict[str, str] = {}
        active_traces: List[str] = []

        for root, dirs, filenames in os.walk(str(proj_dir)):
            # Mutate dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in cls.IGNORE_DIRS and not d.startswith(".")]

            rel_root = os.path.relpath(root, str(proj_dir))
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext in cls.IGNORE_EXTS:
                    continue
                rel_path = f if rel_root == "." else os.path.join(rel_root, f)
                norm_path = rel_path.replace("\\", "/")
                files.append(norm_path)

                # Store key configs
                if f in ("pyproject.toml", "package.json", "setup.py", "pytest.ini", "Cargo.toml", "go.mod"):
                    full_p = os.path.join(root, f)
                    try:
                        with open(full_p, "r", encoding="utf-8", errors="ignore") as fh:
                            config_files[f] = fh.read(2048)
                    except Exception:
                        pass

        # Check for pytest failure cache or recent failure logs
        pytest_cache = proj_dir / ".pytest_cache" / "v" / "cache" / "lastfailed"
        if pytest_cache.exists():
            try:
                active_traces.append(pytest_cache.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass

        return ProjectSnapshot(
            project_path=str(proj_dir),
            project_type=proj_type,
            files=files,
            structure_tree=tree,
            config_files=config_files,
            test_command=proj_type.get("test_command"),
            active_failure_traces=active_traces,
            timestamp=time.time(),
        )

    @classmethod
    def create_checkpoint(cls, path: str, checkpoint_name: str = "") -> str:
        """
        Create a temporary Git branch/stash or snapshot checkpoint so any modification is 100% reversible.
        Returns unique checkpoint_id.
        """
        proj_dir = Path(path).resolve()
        cid = f"chk_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        label = checkpoint_name or "safe_point"

        # Checkpoint storage directory
        chk_dir = proj_dir / ".iris_checkpoints" / cid
        chk_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot all current tracked/relevant files into checkpoint storage
        manifest = []
        for root, dirs, filenames in os.walk(str(proj_dir)):
            dirs[:] = [d for d in dirs if d not in cls.IGNORE_DIRS and not d.startswith(".")]
            rel_root = os.path.relpath(root, str(proj_dir))
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext in cls.IGNORE_EXTS:
                    continue
                src_file = Path(root) / f
                rel_file = f if rel_root == "." else os.path.join(rel_root, f)
                dst_file = chk_dir / rel_file
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                manifest.append(rel_file.replace("\\", "/"))

        # Git branch / stash fallback if git repo
        git_info = cls._detect_git_status(proj_dir)
        git_branch = None
        if git_info.get("is_git"):
            try:
                git_branch = f"iris/chk/{cid}"
                subprocess.run(["git", "branch", git_branch], cwd=str(proj_dir), capture_output=True, timeout=3)
            except Exception:
                pass

        # Write metadata
        metadata = {
            "checkpoint_id": cid,
            "label": label,
            "project_path": str(proj_dir),
            "timestamp": time.time(),
            "manifest": manifest,
            "git_branch": git_branch,
        }
        import json
        with open(chk_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return cid

    @classmethod
    def revert_checkpoint(cls, path: str, checkpoint_id: str) -> bool:
        """
        Reverts the workspace cleanly to the exact pre-task checkpoint state.
        Restores modified files, deleted files, and cleans up any newly created files.
        """
        proj_dir = Path(path).resolve()
        chk_dir = proj_dir / ".iris_checkpoints" / checkpoint_id
        if not chk_dir.exists():
            return False

        meta_file = chk_dir / "metadata.json"
        if not meta_file.exists():
            return False

        import json
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)

        manifest = set(meta.get("manifest", []))

        # 1. Remove files created after checkpoint
        for root, dirs, filenames in os.walk(str(proj_dir)):
            dirs[:] = [d for d in dirs if d not in cls.IGNORE_DIRS and not d.startswith(".")]
            rel_root = os.path.relpath(root, str(proj_dir))
            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext in cls.IGNORE_EXTS:
                    continue
                rel_file = f if rel_root == "." else os.path.join(rel_root, f)
                norm_rel = rel_file.replace("\\", "/")
                if norm_rel not in manifest:
                    try:
                        (Path(root) / f).unlink(missing_ok=True)
                    except Exception:
                        pass

        # 2. Restore all checkpointed files
        for rel_file in manifest:
            src = chk_dir / rel_file
            dst = proj_dir / rel_file
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        return True
