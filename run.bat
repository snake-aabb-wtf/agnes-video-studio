@echo off
REM Agnes Video Studio launcher
REM Three-stage check: venv -> dependencies -> run

setlocal
cd /d "%~dp0"

set VENV_DIR=.venv
set VENV_PY=%VENV_DIR%\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo [1/3] Virtual environment not found. Creating %VENV_DIR% ...
    python -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [X] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo       Virtual environment created.
) else (
    echo [1/3] Virtual environment found.
)

"%VENV_PY%" -c "import PySide6, httpx, PIL, qtawesome, platformdirs" >nul 2>nul
if errorlevel 1 (
    echo [2/3] Dependencies missing. Installing from requirements.txt ...
    "%VENV_PY%" -m pip install --upgrade pip >nul 2>nul
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [X] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo       Dependencies installed.
) else (
    echo [2/3] Dependencies OK.
)

echo [3/3] Starting Agnes Video Studio ...
"%VENV_PY%" video_gui.py
set RC=%errorlevel%

if not %RC%==0 (
    echo.
    echo [X] Program exited with code %RC%.
    pause
)

endlocal
