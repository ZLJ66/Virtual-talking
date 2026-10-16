@echo off
setlocal EnableExtensions
title AI English Simulator - Launcher

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

echo.
echo  ==============================================
echo    AI Immersive English Simulator - Launcher
echo  ==============================================
echo.

echo  [1/4] Checking Python ...
where python >nul 2>&1
if errorlevel 1 (
    echo  [X] python not found. Install Python 3.x and check "Add to PATH".
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo       %%v

echo  [2/4] Checking Node.js / pnpm ...
where node >nul 2>&1
if errorlevel 1 (
    echo  [X] node not found. Install Node.js and add it to PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo       Node %%v
where pnpm >nul 2>&1
if errorlevel 1 (
    echo       Installing pnpm ...
    call npm install -g pnpm
)
for /f "tokens=*" %%v in ('pnpm --version 2^>^&1') do echo       pnpm %%v

echo.
echo  [3/4] Checking backend environment ...
if exist "%ROOT%\backend\.venv\Scripts\python.exe" (
    echo       venv ready
) else (
    echo       First run: creating venv and installing deps, 1-3 min ...
    python -m venv "%ROOT%\backend\.venv"
    if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
        echo  [X] venv creation failed. Use official Python 3.x from python.org
        pause
        exit /b 1
    )
    "%ROOT%\backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT%\backend\requirements.txt"
    if errorlevel 1 (
        echo  [X] backend dependency install failed
        pause
        exit /b 1
    )
    echo       backend environment ready
)

echo  [4/4] Checking frontend dependencies ...
if exist "%ROOT%\frontend\node_modules" (
    echo       node_modules ready
) else (
    echo       First run: installing frontend deps, 1-3 min ...
    pushd "%ROOT%\frontend"
    call pnpm install
    popd
    if errorlevel 1 (
        echo  [X] frontend dependency install failed
        pause
        exit /b 1
    )
    echo       frontend deps ready
)

echo.
echo  Freeing ports 8000 / 5173 if occupied by old instances ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1

echo  Starting backend (FastAPI :8000) ...
pushd "%ROOT%\backend"
start "AI-Backend" .venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
popd

ping -n 3 127.0.0.1 >nul

echo  Starting frontend (Vite :5173) ...
pushd "%ROOT%\frontend"
start "AI-Frontend" cmd /k "pnpm dev"
popd

ping -n 8 127.0.0.1 >nul

echo.
echo  ==============================================
echo    Ready!
echo.
echo    Frontend: http://localhost:5173
echo    Backend:  http://localhost:8000/api/health
echo.
echo    Services run in AI-Backend / AI-Frontend windows.
echo    To stop: just close those two windows.
echo  ==============================================
echo.

start "" http://localhost:5173

echo  This launcher window can be closed anytime.
pause >nul