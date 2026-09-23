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
echo Story Auto: http://127.0.0.1:8765/
echo Keep this window open while using Story Auto. Press Ctrl+C to stop it.
python -m story_auto --runtime-root "%~dp0runtime" ui --host 127.0.0.1 --port 8765
if errorlevel 1 (
  echo Story Auto did not start. Check that Python dependencies are installed and port 8765 is free.
  pause
  exit /b 1
)
