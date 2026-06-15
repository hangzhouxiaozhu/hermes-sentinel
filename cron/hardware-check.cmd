@echo off
REM Hermes Sentinel — Windows scheduled task wrapper
REM Created by install.ps1
python3 -c "import sys; sys.path.insert(0,'%USERPROFILE%\\.hermes\\skills\\system\\hermes-sentinel\\scripts'); from guardian_core import guardian_tick; r=guardian_tick(); print(r.get('message','') if r.get('notify') else '')"
