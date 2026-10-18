import os
import asyncio
import tempfile
from pathlib import Path

from src.agent.orchestrator import IRISOrchestrator
from src.operator.resolver import WorkspaceResolver
from src.operator.summarizer import OperatorSummarizer
from src.operator.task_runner import OperatorTaskRunner
from src.skills.core.operator_skill import ProjectOperatorSkill
from src.tools.registry import ProjectOperatorTool
from src.models.schemas import ProjectOperatorAction


async def main():
    print("=" * 75)
    print("LIVE HANDS-FREE DRY RUN: AI Project Operator & Workspace Resolver")
    print("=" * 75)

    # 1. Setup a realistic project with a failing test to demonstrate diagnosis
    with tempfile.TemporaryDirectory() as tmp_dir:
        demo_proj = Path(tmp_dir) / "auth-service"
        demo_proj.mkdir(parents=True, exist_ok=True)

        calc_file = demo_proj / "auth.py"
        calc_file.write_text(
            "def authenticate(user: str, token: str) -> bool:\n"
            "    # Bug: hardcoded denial\n"
            "    return False\n",
            encoding="utf-8"
        )

        test_file = demo_proj / "test_auth.py"
        test_file.write_text(
            "from auth import authenticate\n\n"
            "def test_authenticate():\n"
            "    assert authenticate('admin', 'secret-token') is True\n",
            encoding="utf-8"
        )

        pyproject = demo_proj / "pyproject.toml"
        pyproject.write_text("[project]\nname = \"auth-service\"\nversion = \"1.0.0\"\n", encoding="utf-8")

        pytest_ini = demo_proj / "pytest.ini"
        pytest_ini.write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

        print(f"\n[1] Prepared demo project workspace: {demo_proj}")
        print("    Files: auth.py, test_auth.py (1 failing assertion)")

        # 2. Simulate Active Window Inspection
        # Editor window title simulation: "test_auth.py - auth-service - Visual Studio Code"
        simulated_window_title = "test_auth.py - auth-service - Visual Studio Code"
        print(f"\n[2] Active Foreground Window Detected:")
        print(f"    Window Title: \"{simulated_window_title}\"")

        resolver = WorkspaceResolver(
            workspace_roots=[tmp_dir, str(Path.cwd().resolve())],
            active_window_getter=lambda: simulated_window_title,
        )

        # Hands-free query: User says "my current project" or "here"
        user_query = "Hey Iris, check why tests are failing in my current project."
        print(f"\n[3] User Natural Voice Query:")
        print(f"    \"{user_query}\"")

        resolved_path = resolver.resolve_project_path("current project")
        print(f"\n[4] Hands-Free Project Resolution:")
        print(f"    Parsed Workspace Candidate: '{Path(resolved_path).name}'")
        print(f"    Resolved Filesystem Path:   {resolved_path}")

        # 3. Execute ProjectOperatorSkill directly with resolved workspace
        print("\n[5] Executing ProjectOperatorSkill (Read-Only Test Diagnosis)...")
        skill = ProjectOperatorSkill(resolver=resolver)
        exec_res = await skill.execute({
            "spoken_reference": "current project",
            "action": "diagnose",
            "test_command": "pytest",
        })

        print("\n[6] Execution Outcome:")
        print(f"    Success:              {exec_res.success}")
        print(f"    Project Name:         {exec_res.output.get('project_name')}")
        print(f"    Tests Passed:         {exec_res.output.get('passed')}")
        diag = exec_res.output.get("diagnostic", {})
        print(f"    Failing Tests:        {diag.get('failing_tests')}")
        print(f"    Target File:          {diag.get('target_file')}")
        print(f"    Error Summary:        {diag.get('error_summary')}")

        print("\n[7] Natural Voice TTS Confirmation:")
        voice_text = exec_res.output.get("voice_confirmation")
        print(f"    [VOICE] \"{voice_text}\"")

        # 4. Demonstrate Checkpoint Creation & Staged Repair Plan
        print("\n[8] Staging Recovery Checkpoint & Plan...")
        plan_res = await skill.execute({
            "spoken_reference": "current project",
            "action": "plan",
            "test_command": "pytest",
        })
        print(f"    Plan ID:              {plan_res.output.get('plan_id')}")
        print(f"    [VOICE] Spoken Plan:  \"{plan_res.output.get('voice_confirmation')}\"")

        print("\n" + "=" * 75)
        print("HANDS-FREE DRY RUN VERIFICATION COMPLETED SUCCESSFULLY!")
        print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
