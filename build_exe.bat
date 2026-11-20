@echo off
rem Build a standalone Windows program into dist\3DMaker\3DMaker.exe
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller --noconfirm --windowed --name 3DMaker ^
  --collect-all build123d --collect-all OCP ^
  --collect-all vtkmodules --collect-all pyvista --collect-all pyvistaqt ^
  --collect-all lib3mf --collect-data ezdxf ^
  --add-data "maker3d/gui/fonts;maker3d/gui/fonts" ^
  launcher.py
echo.
echo Done: dist\3DMaker\3DMaker.exe
pause
