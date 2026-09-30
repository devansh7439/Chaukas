@echo off
rem Chaukas one-click install: double-click this file.
rem   1. installs uv (a small Python installer from astral.sh) if it is missing, after asking
rem   2. installs Chaukas and downloads its models (the only time Chaukas uses the network)
rem   3. puts a "Chaukas" shortcut on the Desktop that starts live protection
cd /d "%~dp0"
echo.
echo  Chaukas - on-device protection against scam calls on this PC
echo  =============================================================
echo.
where uv >nul 2>nul
if errorlevel 1 (
  echo Chaukas is installed with uv, a small Python installer from https://astral.sh/uv
  choice /c YN /m "Install uv for this Windows user now"
  if errorlevel 2 (echo Nothing was installed. & pause & exit /b 1)
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  if errorlevel 1 (echo uv could not be installed. & pause & exit /b 1)
)
rem uv's installer puts it here; a new window would find it on PATH anyway
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
echo.
echo Installing Chaukas and downloading its models (about 1 GB, once)...
uv sync --extra ui --extra context --extra audio --extra asr
if errorlevel 1 (echo The installation failed; see the messages above. & pause & exit /b 1)
uv run chaukas setup
if errorlevel 1 (echo The model download failed; run install.bat again. & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Chaukas.lnk');" ^
  "$s.TargetPath = '%~dp0run.bat'; $s.WorkingDirectory = '%~dp0';" ^
  "$s.IconLocation = '%~dp0src\chaukas\ui\assets\chaukas.ico'; $s.Description = 'Chaukas: protection against scam calls';" ^
  "$s.Save()"
echo.
echo Done. Start Chaukas from the "Chaukas" icon on your Desktop.
pause
