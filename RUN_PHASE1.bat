@echo off
rem Double-click to run Hollow Hull Phase 1 (Blender kit -> layout -> Unreal level).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_phase1.ps1" %*
echo.
echo You can close this window. Unreal stays open.
echo If Unreal closes by itself, double-click COLLECT_LOGS.bat and send Claude what it shows.
pause
