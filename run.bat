@echo off
rem Double-click to start 3D Maker (first run installs everything).
cd /d "%~dp0"
if not exist .venv (
  echo Creating Python environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw -m maker3d %*
