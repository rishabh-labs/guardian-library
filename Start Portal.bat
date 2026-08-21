@echo off
title Fund Library
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment missing. Creating it now...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo.
echo   Fund Library starting...
echo   Open http://localhost:5055 in your browser.
echo   Close this window to stop it.
echo.

start "" http://localhost:5055
.venv\Scripts\python.exe app.py

pause
