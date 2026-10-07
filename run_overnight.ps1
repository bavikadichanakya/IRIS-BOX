$ErrorActionPreference = "Continue"

# Configure API Key
$env:GEMINI_API_KEY = "AQ.Ab8RN6IsDMpD9Zt-EQ2Er4Yc6Df8_4d-dt7WjyCVJDvjjCRi9g"

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

foreach ($task in $tasks) {
    Write-Host "`n==========================================================" -ForegroundColor Cyan
    Write-Host "Executing: $($task.Name) at$(Get-Date)" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    # Execute Aider for the task milestone
    uvx --python 3.12 --from aider-chat aider.exe @AiderFlags --message-file $task.FullName

    $lastCommit = git log -1 --oneline
    Write-Host "Completed $($task.Name) ->$lastCommit" -ForegroundColor Green

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
