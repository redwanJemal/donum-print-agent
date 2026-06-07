# Donum Print Agent - Windows Task Scheduler Installation
# Run this script as Administrator

param(
    [string]$PythonPath = "",
    [switch]$Uninstall
)

# Check for Administrator privileges
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script requires Administrator privileges." -ForegroundColor Red
    Write-Host ""
    Write-Host "Please run PowerShell as Administrator:" -ForegroundColor Yellow
    Write-Host "  1. Right-click PowerShell -> 'Run as administrator'"
    Write-Host "  2. cd to this directory"
    Write-Host "  3. Run: .\install-service.ps1"
    Write-Host ""
    exit 1
}

$TaskName = "DonumPrintAgent"
$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AgentScript = Join-Path $AgentDir "agent.py"

# Uninstall if requested -- removes EVERY autostart method and stops the agent,
# so a machine with any prior setup (boot task and/or login launcher) ends clean.
if ($Uninstall) {
    Write-Host "Removing Donum Print Agent setup..."

    # 1) Scheduled tasks: the boot task plus any leftover self-test task.
    foreach ($t in @($TaskName, 'DonumPrintSelftest', 'DonumSelftest')) {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
            Write-Host "  Removed scheduled task: $t"
        }
    }

    # 2) Per-user login launcher (Startup-folder shortcut).
    $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Donum Print Agent.lnk'
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "  Removed Startup shortcut: $lnk" }

    # 3) Stop launcher loops first (so they don't relaunch the agent), then the agent.
    Get-CimInstance Win32_Process -Filter "Name='wscript.exe' OR Name='cmd.exe'" |
        Where-Object { $_.CommandLine -like '*run-hidden*' -or $_.CommandLine -like '*run-forever*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "  Stopped launcher PID $($_.ProcessId)" }
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*agent.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "  Stopped agent PID $($_.ProcessId)" }

    Write-Host "Done. All agent autostart entries removed and the agent stopped." -ForegroundColor Green
    exit 0
}

# Find Python if not specified
if (-not $PythonPath) {
    $PythonPath = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    if (-not $PythonPath) {
        $PythonPath = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
        if ($PythonPath) {
            # Convert python.exe to pythonw.exe (no console window)
            $PythonPath = $PythonPath -replace "python\.exe$", "pythonw.exe"
        }
    }
}

if (-not $PythonPath -or -not (Test-Path $PythonPath)) {
    Write-Error "Could not find Python. Please specify path: .\install-service.ps1 -PythonPath 'C:\path\to\pythonw.exe'"
    exit 1
}

Write-Host "=== Donum Print Agent Installer ===" -ForegroundColor Cyan
Write-Host "Agent directory: $AgentDir"
Write-Host "Python path: $PythonPath"
Write-Host "Agent script: $AgentScript"
Write-Host ""

# Check if .env exists
$EnvFile = Join-Path $AgentDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Warning ".env file not found. Make sure to create it before starting the agent."
}

# Remove existing task if present
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing existing task..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the scheduled task
Write-Host "Creating scheduled task..."

$action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$AgentScript`"" `
    -WorkingDirectory $AgentDir

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Donum QMS Print Agent - Connects to backend and prints token receipts"

Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null

Write-Host ""
Write-Host "Task '$TaskName' created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Commands:" -ForegroundColor Yellow
Write-Host "  Start now:    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Stop:         Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Check status: Get-ScheduledTask -TaskName '$TaskName' | Select-Object State"
Write-Host "  View logs:    Get-Content '$AgentDir\print-agent.log' -Tail 50"
Write-Host "  Uninstall:    .\install-service.ps1 -Uninstall"
Write-Host ""

# Ask if user wants to start now
$start = Read-Host "Start the agent now? (Y/n)"
if ($start -ne "n" -and $start -ne "N") {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 2
    $state = (Get-ScheduledTask -TaskName $TaskName).State
    Write-Host "Agent state: $state" -ForegroundColor Cyan
}
