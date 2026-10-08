$ErrorActionPreference = "Continue"

$AiderModel = "openrouter/dots-studio/dots-3-note-preview:free"
$AiderFlags = @(
    "--model", $AiderModel,
    "--yes-always",
    "--auto-test",
    "--test-cmd", "uv run --python 3.12 pytest -o pythonpath=.",
    "--no-show-release-notes"
)

$pipeline = @(
    @{ Task = "tasks\05_lifespan_and_keepalive.md"; Files = @("src\server\app.py", "tests\test_server.py") },
    @{ Task = "tasks\06_streaming_tts.md";          Files = @("src\models\schemas.py", "src\agent\orchestrator.py", "src\server\app.py", "tests\test_streaming.py") },
    @{ Task = "tasks\07_multi_turn_memory.md";      Files = @("src\agent\orchestrator.py", "tests\test_memory.py") },
    @{ Task = "tasks\08_simulator_and_docs.md";     Files = @("scripts\simulate_speaker.py", "README.md") }
)

Write-Host "=== Starting Autonomous Pipeline at $(Get-Date) ===" -ForegroundColor Green

foreach ($step in$pipeline) {
    $taskPath =$step.Task
    $targetFiles =$step.Files

    Write-Host "`n==========================================================" -ForegroundColor Cyan
    Write-Host "Starting: $taskPath at $(Get-Date)" -ForegroundColor Cyan
    Write-Host "Targets: $($targetFiles -join ', ')" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    $fileArgs = @()
    foreach ($f in $targetFiles) {
        $fileArgs += "--file"
        $fileArgs += $f
    }

    uvx --python 3.12 --from aider-chat aider.exe @AiderFlags @fileArgs --message-file $taskPath

    $lastCommit = git log -1 --oneline
    Write-Host "Completed $taskPath -> $lastCommit" -ForegroundColor Green

    Write-Host "Pushing progress to GitHub (main)..." -ForegroundColor Yellow
    git push origin main

    Start-Sleep -Seconds 10
}

Write-Host "`n=== All Autonomous Tasks Completed at $(Get-Date) ===" -ForegroundColor Green
git push origin main
git log --oneline -n 12
