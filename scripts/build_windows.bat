@echo off
REM Build RetroSpecs as a standalone Windows executable using PyInstaller.

cd /d "%~dp0\.."

pip install pyinstaller

pyinstaller ^
    --onefile ^
    --name retrospecs ^
    --windowed ^
    --hidden-import=OpenGL.platform.win32 ^
    --add-data "retrospecs;retrospecs" ^
    retrospecs\__main__.py

echo.
echo Build complete: dist\retrospecs.exe
