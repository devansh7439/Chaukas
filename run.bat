@echo off
rem Chaukas: live protection for calls on this PC.
rem   run.bat setup   first time: install everything and download the speech model
rem   run.bat         start protecting (options pass through, e.g. run.bat --language hi)
cd /d "%~dp0"
where uv >nul 2>nul || (echo Chaukas needs uv: https://docs.astral.sh/uv/getting-started/installation/ & pause & exit /b 1)
if /i "%~1"=="setup" (
  uv sync --extra ui --extra context --extra audio --extra asr || (pause & exit /b 1)
  uv run chaukas setup
  pause
  exit /b
)
uv run --extra ui --extra context --extra audio --extra asr chaukas run %*
