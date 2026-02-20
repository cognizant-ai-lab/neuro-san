@echo off
REM Neuro SAN Client quick start Script for Windows
REM This script starts the Neuro SAN CLI client

setlocal enabledelayedexpansion

echo ===============================================
echo   Neuro SAN Client quick start
echo ===============================================
echo.

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
cd /d "%PROJECT_DIR%"

REM Activate virtual environment
if exist ".venv" (
    set VENV_DIR=.venv
) else if exist "venv" (
    set VENV_DIR=venv
) else (
    echo Virtual environment not found!
    echo Please run start-server.bat first to set up the environment.
    pause
    exit /b 1
)

echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate virtual environment
    pause
    exit /b 1
)
echo Virtual environment activated
echo.

REM Set PYTHONPATH
set PYTHONPATH=%PROJECT_DIR%

REM Get agent name from command line argument or use default
set AGENT_NAME=%1
if "%AGENT_NAME%"=="" set AGENT_NAME=hello_world

REM Check if connecting to server or running direct
if "%2"=="--server" goto server_mode
if "%2"=="--http" goto server_mode
goto direct_mode

:server_mode
echo Connecting to server mode...
echo Make sure the server is running (start-server.bat)
echo.
python -m neuro_san.client.agent_cli --http --agent %AGENT_NAME%
goto end

:direct_mode
echo Running in direct mode (no server)...
echo.
python -m neuro_san.client.agent_cli --agent %AGENT_NAME%

:end
pause
