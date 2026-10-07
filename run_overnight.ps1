$ErrorActionPreference = "Continue"

if (-not $env:GEMINI_API_KEY) {
    Write-Host "ERROR: Please set your GEMINI_API_KEY first!" -ForegroundColor Red
    Write-Host "Run: `$env:GEMINI_API_KEY='your_api_key_here'" -ForegroundColor Yellow
    exit 1
}

$AiderModel = "gemini/gemini-2.5-pro"
$AiderFlags = @(
    "--model", $AiderModel,
    "--yes-always",
    "--auto-test",
    "--test-cmd", "uv run --python 3.12 pytest",
    "--no-show-release-notes"
)

Write-Host "=== Starting Overnight Aider Pipeline at $(Get-Date) ===" -ForegroundColor Green

$tasks = Get-ChildItem -Path "tasks\*.md" | Sort-Object Name

foreach ($task in$tasks) {
    Write-Host "`n==========================================================" -ForegroundColor Cyan
    Write-Host "Executing: $($task.Name) at $(Get-Date)" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    uvx --python 3.12 --from aider-chat aider.exe @AiderFlags --message-file $task.FullName

    $lastCommit = git log -1 --oneline
    Write-Host "Completed $($task.Name) -> $lastCommit" -ForegroundColor Green
    Start-Sleep -Seconds 3
}

Write-Host "`n=== All tasks finished at $(Get-Date) ===" -ForegroundColor Green
Write-Host "Final Git Log:" -ForegroundColor Yellow
git log --oneline -n 10
