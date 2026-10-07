@echo off
rem Double-click after Unreal closes unexpectedly: gathers crash info for Claude.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect_logs.ps1" %*
echo.
pause
