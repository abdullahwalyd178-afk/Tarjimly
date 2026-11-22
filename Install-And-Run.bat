@echo off
REM ============================================================
REM  Tarjimly - screen translator. One-click installer + launcher.
REM ============================================================
cd /d "%~dp0"
title Tarjimly

REM ---- 1. Tesseract (the local OCR engine) ---------------------
set TESS=
where tesseract >nul 2>nul && set TESS=1
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set TESS=1
if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" set TESS=1
if exist "%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe" set TESS=1
if not defined TESS (
    echo [Tarjimly] Tesseract OCR is not installed. Trying winget...
    where winget >nul 2>nul
    if errorlevel 1 goto :tess_manual
    winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :tess_manual
)
goto :python

:tess_manual
echo.
echo [Tarjimly] Please install Tesseract manually:
echo   https://github.com/UB-Mannheim/tesseract/wiki
echo Keep the default install folder, then run this file again.
start https://github.com/UB-Mannheim/tesseract/wiki
pause
exit /b 1

:python
REM ---- 2. Skip setup only if a previous install FINISHED --------
if exist ".venv\Scripts\python.exe" if exist ".venv\.installed" goto :run

REM ---- 3. Find a supported Python (3.9 - 3.13) ------------------
set PY=
where py >nul 2>nul
if not errorlevel 1 (
    for %%V in (3.12 3.11 3.13 3.10 3.9) do (
        if not defined PY (
            py -%%V -c "import tkinter" >nul 2>nul && set PY=py -%%V
        )
    )
)
if not defined PY (
    python -c "import sys, tkinter; sys.exit(0 if sys.version_info[0]==3 and sys.version_info[1]>=9 else 1)" >nul 2>nul && set PY=python
)
if not defined PY (
    echo.
    echo [Tarjimly] No usable Python found ^(need 3.9 or newer with Tk^).
    echo Download Python from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM ---- 4. (Re)create the virtual environment ---------------------
if exist ".venv" (
    echo [Tarjimly] Previous setup was incomplete - rebuilding...
    rmdir /s /q ".venv"
)
echo [Tarjimly] First run: preparing the environment...
%PY% -m venv .venv
if errorlevel 1 (
    echo [Tarjimly] Could not create the virtual environment.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [Tarjimly] Package installation failed. Check your internet and run again.
    pause
    exit /b 1
)
echo ok> ".venv\.installed"

:run
call ".venv\Scripts\activate.bat"
echo.
echo [Tarjimly] Starting. Ctrl+Alt+T = select area  /  Ctrl+Alt+S = translate selected text
echo.
python tarjimly.py %*
if errorlevel 1 pause
