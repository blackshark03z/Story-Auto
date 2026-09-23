@echo off
setlocal
cd /d "%~dp0"
where python.exe >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 is required. See README.md.
  pause
  exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo This release requires Python 3.11. See README.md.
  pause
  exit /b 1
)
python tools\launch_story_auto.py
set "story_auto_exit=%errorlevel%"
if "%story_auto_exit%"=="2" (
  pause
  exit /b 0
)
if not "%story_auto_exit%"=="0" (
  echo Story Auto did not start. Check Python dependencies and the port message above.
  pause
  exit /b 1
)
