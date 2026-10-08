$ErrorActionPreference = "Continue"

# Primary Free Model on OpenRouter
$AiderModel = "openrouter/dots-studio/dots-3-note-preview:free"

$AiderFlags = @(
    "--model", $AiderModel,
    "--yes-always",
    "--auto-test",
    "--test-cmd", "uv run --python 3.12 pytest -o pythonpath=.",
    "--no-show-release-notes"
)

Write-Host "=== Starting 100% Free OpenRouter Overnight Pipeline at $(Get-Date) ===" -ForegroundColor Green
Write-Host "Active Model: $AiderModel" -ForegroundColor Yellow

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

    # Execute Aider using OpenRouter Free
    uvx --python 3.12 --from aider-chat aider.exe @AiderFlags @fileArgs --message-file $taskPath

    $lastCommit = git log -1 --oneline
    Write-Host "Completed $taskPath ->$lastCommit" -ForegroundColor Green

    # Push progress incrementally to GitHub
    Write-Host "Pushing progress to GitHub (main)..." -ForegroundColor Yellow
    git push -u origin main

    Start-Sleep -Seconds 5
}

Write-Host "`n=== All tasks finished at $(Get-Date) ===" -ForegroundColor Green
Write-Host "Final push to GitHub..." -ForegroundColor Yellow
git push -u origin main

Write-Host "`nFinal Git Log Summary:" -ForegroundColor Yellow
git log --oneline -n 10
