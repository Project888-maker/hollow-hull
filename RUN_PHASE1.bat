@echo off
rem Double-click to run Hollow Hull Phase 1 (Blender kit -> layout -> Unreal level).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_phase1.ps1" %*
echo.
pause
