@echo off
REM Hermes Sentinel — Windows daily report scheduled task wrapper
REM Created by install.ps1
python3 -c "import sys; sys.path.insert(0,'%USERPROFILE%\\.hermes\\skills\\system\\hermes-sentinel\\scripts'); from guardian_core import guardian_tick, guardian_daily_report; guardian_tick(); print(guardian_daily_report())"
