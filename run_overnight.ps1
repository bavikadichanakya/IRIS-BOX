$ErrorActionPreference = "Continue"

$env:GEMINI_API_KEY = "AQ.Ab8RN6IsDMpD9Zt-EQ2Er4Yc6Df8_4d-dt7WjyCVJDvjjCRi9g"

$AiderModel = "gemini/gemini-2.5-flash"
$AiderFlags = @(
    "--model", $AiderModel,
    "--yes-always",
    "--auto-test",
    "--test-cmd", "uv run --python 3.12 pytest -o pythonpath=.",
    "--no-show-release-notes"
)

Write-Host "=== Starting Overnight Aider Pipeline at $(Get-Date) ===" -ForegroundColor Green

$pipeline = @(
    @{ Task = "tasks\01_models_and_schemas.md"; Files = @("src\models\schemas.py", "tests\test_schemas.py") },
    @{ Task = "tasks\02_tool_registry.md";      Files = @("src\models\schemas.py", "src\tools\registry.py", "tests\test_tools.py") },
    @{ Task = "tasks\03_orchestrator_router.md"; Files = @("src\models\schemas.py", "src\tools\registry.py", "src\agent\orchestrator.py", "tests\test_orchestrator.py") },
    @{ Task = "tasks\04_websocket_server.md";   Files = @("src\agent\orchestrator.py", "src\server\app.py", "tests\test_server.py") }
)

foreach ($step in $pipeline) {
    $taskPath = $step.Task
    $targetFiles = $step.Files

    Write-Host "`n==========================================================" -ForegroundColor Cyan
    Write-Host "Executing: $taskPath at$(Get-Date)" -ForegroundColor Cyan
    Write-Host "Targets: $($targetFiles -join ', ')" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    $fileArgs = @()
    foreach ($f in $targetFiles) {$fileArgs += "--file"
        $fileArgs +=$f
    }

    uvx --python 3.12 --from aider-chat aider.exe @AiderFlags @fileArgs --message-file $taskPath

    $lastCommit = git log -1 --oneline
    Write-Host "Completed $taskPath ->$lastCommit" -ForegroundColor Green

    Write-Host "Pushing progress to GitHub (main)..." -ForegroundColor Yellow
    git push -u origin main

    Start-Sleep -Seconds 5
}

Write-Host "`n=== All tasks finished at $(Get-Date) ===" -ForegroundColor Green
Write-Host "Final push to GitHub..." -ForegroundColor Yellow
git push -u origin main

Write-Host "`nFinal Git Log Summary:" -ForegroundColor Yellow
git log --oneline -n 10
