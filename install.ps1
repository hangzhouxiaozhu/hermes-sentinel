<#
.SYNOPSIS
    Hermes Sentinel — Windows installation script.
    Creates scheduled tasks (Task Scheduler) instead of cron.
.DESCRIPTION
    - Copies files to %USERPROFILE%\.hermes\skills\system\hermes-sentinel\
    - Creates a scheduled task for hardware/network patrol (every 15 minutes)
    - Creates a scheduled task for daily report (9:00 AM)
    - Runs initial validation
.NOTES
    Run this in PowerShell as the normal user (not Administrator).
    Scheduled tasks are created at the user level — no admin required.
#>

$ErrorActionPreference = "Stop"
$SkillName = "hermes-sentinel"
$SkillDir = "$env:USERPROFILE\.hermes\skills\system\$SkillName"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = (Get-Command python3 -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Python) { $Python = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" }

Write-Host "==============================" -ForegroundColor Cyan
Write-Host " Hermes Sentinel · Install" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan

# ── Check Python ──
if (-not (Test-Path $Python)) {
    Write-Host "❌ Python not found at $Python" -ForegroundColor Red
    Write-Host "   Install Python 3 from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}
Write-Host "✅ Python: $Python" -ForegroundColor Green
Write-Host "✅ Source: $SourceDir"
Write-Host "✅ Target: $SkillDir"

# ── Copy files ──
Write-Host ""
Write-Host "📦 Copying files ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "$SkillDir\scripts" | Out-Null
Copy-Item -Recurse -Force "$SourceDir\scripts\*.py" "$SkillDir\scripts\"
if (Test-Path "$SourceDir\cron") {
    Copy-Item -Recurse -Force "$SourceDir\cron" "$SkillDir\"
}
if (Test-Path "$SourceDir\plugin") {
    $PluginDir = "$env:USERPROFILE\.hermes\plugins\hermes-sentinel"
    New-Item -ItemType Directory -Force -Path $PluginDir | Out-Null
    Copy-Item -Recurse -Force "$SourceDir\plugin\*" $PluginDir
    Write-Host "✅ Plugin installed to $PluginDir"
}
if (Test-Path "$SourceDir\templates") {
    Copy-Item -Recurse -Force "$SourceDir\templates" "$SkillDir\"
}
if (Test-Path "$SourceDir\SKILL.md") {
    Copy-Item -Force "$SourceDir\SKILL.md" "$SkillDir\"
}
Write-Host "✅ Files copied"

# ── Create log directories ──
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.hermes\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.hermes\cache\guardian" | Out-Null

# ── Schedule tasks (Task Scheduler instead of cron) ──
Write-Host ""
Write-Host "⏰ Creating scheduled tasks ..." -ForegroundColor Yellow

$TickScript = "$SkillDir\cron\hardware-check.cmd"
$DailyScript = "$SkillDir\cron\daily-backup.cmd"

# Create CMD wrappers for scheduled tasks (more reliable than PS1 in task scheduler)
@"
@echo off
"%PYTHON%" -c "import sys; sys.path.insert(0,'$SkillDir\scripts'); from guardian_core import guardian_tick; r=guardian_tick(); print(r.get('message','') if r.get('notify') else '')"
"@ | Out-File -FilePath $TickScript -Encoding utf8 -Force

@"
@echo off
"%PYTHON%" -c "import sys; sys.path.insert(0,'$SkillDir\scripts'); from guardian_core import guardian_tick, guardian_daily_report; guardian_tick(); print(guardian_daily_report())"
"@ | Out-File -FilePath $DailyScript -Encoding utf8 -Force

# Register scheduled tasks (user-level, no admin needed)
$TaskName = "HermesSentinel-Patrol"
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "  ⏭️  Patrol task already exists, skip" -ForegroundColor Yellow
} else {
    $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$TickScript`""
    $Trigger = New-ScheduledTaskTrigger -Daily -At "00:00" -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 365)
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Force | Out-Null
    Write-Host "  ✅ Patrol task created (every 15 min)" -ForegroundColor Green
}

$TaskName2 = "HermesSentinel-DailyReport"
$Existing2 = Get-ScheduledTask -TaskName $TaskName2 -ErrorAction SilentlyContinue
if ($Existing2) {
    Write-Host "  ⏭️  Daily report task already exists, skip" -ForegroundColor Yellow
} else {
    $Action2 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$DailyScript`""
    $Trigger2 = New-ScheduledTaskTrigger -Daily -At "09:00AM"
    $Principal2 = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName2 -Action $Action2 -Trigger $Trigger2 -Principal $Principal2 -Force | Out-Null
    Write-Host "  ✅ Daily report task created (9:00 AM)" -ForegroundColor Green
}

# ── Initial validation ──
Write-Host ""
Write-Host "🚀 Running initial validation ..." -ForegroundColor Yellow
& $Python -c @"
import sys
sys.path.insert(0, '$SkillDir\scripts'.replace('\\', '/'))
from os_detect import get_platform_name, get_python_version
from guardian_core import guardian_tick

print(f'  Platform: {get_platform_name()}')
print(f'  Python:   {get_python_version()}')
result = guardian_tick()
if result.get('notify'):
    print(f'  🌟 Notification: {result.get("message","")[:80]}')
else:
    print('  ✅ First patrol completed')
print('  📝 Logs: %USERPROFILE%\\.hermes\\logs\\')
" 2>&1

Write-Host ""
Write-Host "==============================" -ForegroundColor Cyan
Write-Host " ✅ Hermes Sentinel installed" -ForegroundColor Green
Write-Host "==============================" -ForegroundColor Cyan
Write-Host ""
Write-Host "View logs:   Get-Content \"`$env:USERPROFILE\\.hermes\\logs\\hardware_monitor.log\" -Tail 5"
Write-Host "View tasks:  Get-ScheduledTask -TaskName HermesSentinel-*"
Write-Host "Manual run:  & $Python -c \"import sys; sys.path.insert(0,'$SkillDir\scripts'.replace('\\','/')); from guardian_core import guardian_tick; guardian_tick()\""
