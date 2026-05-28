@echo off
setlocal EnableExtensions
cd /d %~dp0

set "LOG_FILE=%~dp0launcher_runtime.log"
set "TMP_PY=%TEMP%\cowcat_python_path.txt"
echo [%date% %time%] launcher start>"%LOG_FILE%"

set "PY_EXE="

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
    echo using local venv: %PY_EXE%>>"%LOG_FILE%"
)

if not defined PY_EXE (
    py -3 -c "import sys; print(sys.executable)" >"%TMP_PY%" 2>nul
    if not errorlevel 1 (
        set /p PY_EXE=<"%TMP_PY%"
        echo using py launcher: %PY_EXE%>>"%LOG_FILE%"
    )
)

if not defined PY_EXE (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PY_EXE=python"
        echo using PATH python>>"%LOG_FILE%"
    )
)

if not defined PY_EXE (
    if exist "D:\Anaconda\python.exe" (
        set "PY_EXE=D:\Anaconda\python.exe"
        echo using fallback anaconda: %PY_EXE%>>"%LOG_FILE%"
    )
)

if exist "%TMP_PY%" del /q "%TMP_PY%" >nul 2>nul

if not defined PY_EXE goto no_python

"%PY_EXE%" -c "import tkinter, imageio, imageio_ffmpeg, PIL" 1>>"%LOG_FILE%" 2>>&1
if errorlevel 1 goto missing_deps

"%PY_EXE%" app.py 1>>"%LOG_FILE%" 2>>&1
if errorlevel 1 goto app_failed

exit /b 0

:no_python
echo.
echo Failed to start: Python 3 was not found on this computer.
echo Please install Python 3, or create a local .venv in this folder.
echo Details are saved to:
echo %LOG_FILE%
pause
exit /b 1

:missing_deps
echo.
echo Failed to start: required Python modules are missing.
echo Required modules: tkinter, Pillow, imageio, imageio_ffmpeg
echo Try running:
echo     python -m pip install -r requirements.txt
echo Details are saved to:
echo %LOG_FILE%
pause
exit /b 1

:app_failed
echo.
echo The assistant exited with an error.
echo Check the log file for details:
echo %LOG_FILE%
pause
exit /b 1
