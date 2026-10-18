import os
import pytest
from pathlib import Path

from src.operator.resolver import WorkspaceResolver, parse_window_title
from src.operator.summarizer import OperatorSummarizer
from src.operator.task_runner import DiagnosticReport
from src.skills.core.operator_skill import ProjectOperatorSkill


@pytest.fixture
def mock_workspace_hierarchy(tmp_path):
    """
    Creates a multi-project directory structure simulating typical developer workspaces.
    """
    roots = tmp_path / "workspaces"
    roots.mkdir(parents=True, exist_ok=True)

    # 1. auth-service project
    auth_dir = roots / "auth-service"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "pyproject.toml").write_text("[project]\nname='auth-service'\n", encoding="utf-8")
    (auth_dir / "test_auth.py").write_text("def test_ok(): assert True\n", encoding="utf-8")

    # 2. iris-backend project
    iris_dir = roots / "iris-backend"
    iris_dir.mkdir(parents=True, exist_ok=True)
    (iris_dir / "pyproject.toml").write_text("[project]\nname='iris-backend'\n", encoding="utf-8")

    # 3. cybersecurity_lab project (with underscore)
    cyber_dir = roots / "cybersecurity_lab"
    cyber_dir.mkdir(parents=True, exist_ok=True)
    (cyber_dir / "README.md").write_text("# Cyber Lab\n", encoding="utf-8")

    # 4. payment-gateway-api
    payment_dir = roots / "payment-gateway-api"
    payment_dir.mkdir(parents=True, exist_ok=True)
    (payment_dir / "package.json").write_text("{\"name\": \"payment-gateway\"}\n", encoding="utf-8")

    return {
        "root": roots,
        "auth_service": auth_dir,
        "iris_backend": iris_dir,
        "cybersecurity_lab": cyber_dir,
        "payment_gateway": payment_dir,
    }


def test_parse_window_title():
    """Verify window title parsing across VS Code, Cursor, PyCharm, and Windows Terminal."""
    # 1. VS Code standard
    assert parse_window_title("test_auth.py - auth-service - Visual Studio Code") == "auth-service"
    assert parse_window_title("auth-service - Visual Studio Code") == "auth-service"

    # 2. VS Code unsaved indicator and workspace suffix
    assert parse_window_title("● main.py - my-app - Visual Studio Code") == "my-app"
    assert parse_window_title("iris-box (Workspace) - Visual Studio Code") == "iris-box"

    # 3. Cursor IDE
    assert parse_window_title("server.ts - auth-service - Cursor") == "auth-service"
    assert parse_window_title("auth-service - Cursor") == "auth-service"

    # 4. PyCharm / IntelliJ
    assert parse_window_title("iris-backend \u2013 test_api.py") == "iris-backend"
    assert parse_window_title("iris-backend [C:\\Projects\\iris-backend] - test_api.py") == "iris-backend"

    # 5. Windows Terminal & PowerShell
    assert parse_window_title("auth-service - Windows Terminal") == "auth-service"
    assert parse_window_title("Windows PowerShell - auth-service") == "auth-service"

    # 6. Edge cases: Empty, None, or whitespace
    assert parse_window_title("") is None
    assert parse_window_title(None) is None
    assert parse_window_title("   ") is None


def test_fuzzy_matching_spoken_alias(mock_workspace_hierarchy):
    """Verify natural spoken aliases match directories under configured WORKSPACE_ROOTS."""
    roots = [str(mock_workspace_hierarchy["root"].resolve())]
    resolver = WorkspaceResolver(workspace_roots=roots)

    # Spoken with spaces matching hyphenated directory: "auth service" -> auth-service
    resolved = resolver.resolve_project_path("auth service")
    assert resolved is not None
    assert Path(resolved).resolve() == mock_workspace_hierarchy["auth_service"].resolve()

    # Substring alias: "auth" -> auth-service
    resolved_sub = resolver.resolve_project_path("auth")
    assert resolved_sub is not None
    assert Path(resolved_sub).resolve() == mock_workspace_hierarchy["auth_service"].resolve()

    # Underscored directory: "cybersecurity lab" -> cybersecurity_lab
    resolved_cyber = resolver.resolve_project_path("cybersecurity lab")
    assert resolved_cyber is not None
    assert Path(resolved_cyber).resolve() == mock_workspace_hierarchy["cybersecurity_lab"].resolve()

    # Prefix alias: "iris" -> iris-backend
    resolved_iris = resolver.resolve_project_path("iris")
    assert resolved_iris is not None
    assert Path(resolved_iris).resolve() == mock_workspace_hierarchy["iris_backend"].resolve()

    # Close fuzzy match (typo / ASR mishearing): "atuh service" -> auth-service
    resolved_typo = resolver.resolve_project_path("atuh service")
    assert resolved_typo is not None
    assert Path(resolved_typo).resolve() == mock_workspace_hierarchy["auth_service"].resolve()


def test_active_window_detection(mock_workspace_hierarchy):
    """Verify active editor title is inspected when reference is omitted."""
    roots = [str(mock_workspace_hierarchy["root"].resolve())]

    # Injected window title getter simulating VS Code active window
    resolver = WorkspaceResolver(
        workspace_roots=roots,
        active_window_getter=lambda: "auth.py - auth-service - Visual Studio Code",
    )

    resolved = resolver.resolve_project_path(None)
    assert resolved is not None
    assert Path(resolved).resolve() == mock_workspace_hierarchy["auth_service"].resolve()


def test_recency_fallback(mock_workspace_hierarchy):
    """Verify recency fallback when user says 'this project', 'my project', or 'here'."""
    roots = [str(mock_workspace_hierarchy["root"].resolve())]
    auth_path = str(mock_workspace_hierarchy["auth_service"].resolve())
    iris_path = str(mock_workspace_hierarchy["iris_backend"].resolve())

    # 1. Fallback via last_active_project_path
    resolver = WorkspaceResolver(
        workspace_roots=roots,
        last_active_project_path=auth_path,
    )

    resolved_this = resolver.resolve_project_path("this project")
    assert resolved_this == auth_path

    resolved_here = resolver.resolve_project_path("here")
    assert resolved_here == auth_path

    resolved_my = resolver.resolve_project_path("my project")
    assert resolved_my == auth_path

    # 2. Fallback via session_state dictionary
    session_state = {"last_project_path": iris_path}
    resolved_session = resolver.resolve_project_path("this project", session_state=session_state)
    assert resolved_session == iris_path


def test_direct_path_match(mock_workspace_hierarchy):
    """Verify direct valid filesystem path is matched immediately and updates recency."""
    roots = [str(mock_workspace_hierarchy["root"].resolve())]
    auth_path = str(mock_workspace_hierarchy["auth_service"].resolve())

    resolver = WorkspaceResolver(workspace_roots=roots)
    resolved = resolver.resolve_project_path(auth_path)

    assert resolved == auth_path
    assert resolver.last_active_project_path == auth_path


def test_ambiguous_project_clarification(mock_workspace_hierarchy):
    """Verify completely unknown or ambiguous references return None and trigger clarification."""
    roots = [str(mock_workspace_hierarchy["root"].resolve())]
    resolver = WorkspaceResolver(workspace_roots=roots)

    # Random unknown project name
    resolved = resolver.resolve_project_path("completely-unknown-project-xyz-999")
    assert resolved is None

    # Clarification prompt verification
    clarification = OperatorSummarizer.prompt_clarification()
    assert clarification == "Which project should I inspect?"


def test_operator_summarizer():
    """Verify OperatorSummarizer produces natural voice summaries."""
    # 1. Passing tests summary
    report_pass = DiagnosticReport(
        project_path="C:/Projects/auth-service",
        test_command="pytest",
        exit_code=0,
        passed=True,
        stdout="1 passed",
        stderr="",
    )
    summary_pass = OperatorSummarizer.summarize_diagnostic(report_pass, project_name="auth-service")
    assert "Inspecting your auth-service project" in summary_pass
    assert "All tests are passing" in summary_pass

    # 2. Failing test summary (1 failure)
    report_fail = DiagnosticReport(
        project_path="C:/Projects/auth-service",
        test_command="pytest",
        exit_code=1,
        passed=False,
        stdout="FAILED test_auth.py::test_login",
        stderr="",
        failing_tests=["test_auth.py::test_login"],
        target_file="test_auth.py",
        error_summary="AssertionError: 401 != 200",
    )
    summary_fail = OperatorSummarizer.summarize_diagnostic(report_fail, project_name="auth-service")
    assert "Inspecting your auth-service project" in summary_fail
    assert "One test failed in test_auth.py" in summary_fail
    assert "AssertionError: 401 != 200" in summary_fail


@pytest.mark.asyncio
async def test_operator_skill_resolution_flow(mock_workspace_hierarchy):
    """Verify ProjectOperatorSkill executes with spoken alias and produces voice confirmation."""
    roots = [str(mock_workspace_hierarchy["root"].resolve())]
    resolver = WorkspaceResolver(workspace_roots=roots)

    skill = ProjectOperatorSkill(resolver=resolver)

    # 1. Resolve via spoken alias: "auth service"
    result = await skill.execute(
        params={
            "spoken_reference": "auth service",
            "test_command": "python -c \"print('1 passed')\"",
        }
    )

    assert result.success is True
    assert result.output["project_name"] == "auth-service"
    assert "Inspecting your auth-service project" in result.output["voice_confirmation"]

    # 2. Ambiguous reference handling: prompts user
    ambiguous_result = await skill.execute(
        params={
            "spoken_reference": "unknown-nonexistent-987654",
        }
    )

    assert ambiguous_result.success is False
    assert ambiguous_result.error == "AMBIGUOUS_PROJECT"
    assert ambiguous_result.output["prompt"] == "Which project should I inspect?"
    assert ambiguous_result.output["voice_confirmation"] == "Which project should I inspect?"
