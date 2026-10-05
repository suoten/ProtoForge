@echo off
REM ProtoForge Windows Service installer (v1.5.0)
REM Uses NSSM (Non-Sucking Service Manager) to run ProtoForge as a real
REM Windows service: auto-start on boot, auto-restart on crash, log rotation.
REM This replaces the fragile VBS autostart approach of v1.3.3.
REM
REM Usage:
REM   scripts\install_service.bat [HTTP_PORT]
REM
REM Prerequisites:
REM   1. Run this script from the ProtoForge project root.
REM   2. NSSM must be available on PATH, or placed at tools\nssm.exe.
REM      Download: https://nssm.cc/download (copy win64\nssm.exe to tools\)
REM   3. Run this script as Administrator.

setlocal EnableDelayedExpansion

set PORT=%1
if "%PORT%"=="" set PORT=18080

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator privileges required.
    echo         Right-click the terminal and choose "Run as administrator".
    exit /b 1
)

set NSSM_EXE=nssm
where nssm >nul 2>&1
if errorlevel 1 (
    if exist "tools\nssm.exe" (
        set NSSM_EXE=%~dp0..\tools\nssm.exe
    ) else (
        echo [ERROR] nssm not found.
        echo   1. Download NSSM from https://nssm.cc/download
        echo   2. Copy win64\nssm.exe to %~dp0..\tools\nssm.exe
        echo   3. Run this script again.
        exit /b 1
    )
)

REM Resolve python: prefer project venv, fall back to PATH
set PYTHON_EXE=%~dp0..\venv\Scripts\python.exe
if not exist "!PYTHON_EXE!" (
    for /f "delims=" %%i in ('where python') do (
        set PYTHON_EXE=%%i
        goto :found_python
    )
    echo [ERROR] Python not found. Install Python 3.10+ first.
    exit /b 1
)
:found_python

set APP_DIR=%~dp0..
for %%i in ("%APP_DIR%") do set APP_DIR=%%~fi

set LOG_DIR=%APP_DIR%\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo Installing ProtoForge service...
echo   python : !PYTHON_EXE!
echo   workdir: %APP_DIR%
echo   port   : %PORT%

!NSSM_EXE! install ProtoForge "!PYTHON_EXE!" -m protoforge run --host 0.0.0.0 --port %PORT%
if errorlevel 1 goto :failed

!NSSM_EXE! set ProtoForge AppDirectory %APP_DIR% >nul
!NSSM_EXE! set ProtoForge AppStdout %LOG_DIR%\service-out.log >nul
!NSSM_EXE! set ProtoForge AppStderr %LOG_DIR%\service-err.log >nul
!NSSM_EXE! set ProtoForge AppRotateFiles 1 >nul
!NSSM_EXE! set ProtoForge AppRotateOnline 1 >nul
!NSSM_EXE! set ProtoForge AppRotateBytes 10485760 >nul
!NSSM_EXE! set ProtoForge AppExit Default Restart >nul
!NSSM_EXE! set ProtoForge AppRestartDelay 5000 >nul
!NSSM_EXE! set ProtoForge DisplayName ProtoForge >nul
!NSSM_EXE! set ProtoForge Description ProtoForge - IoT protocol simulation and testing platform >nul
!NSSM_EXE! set ProtoForge Start SERVICE_AUTO_START >nul

REM Admin password for the service: generate one and print it
!NSSM_EXE! set ProtoForge AppEnvironmentExtra PROTOFORGE_ADMIN_PASSWORD=ProtoForge-Service-Please-Change-Me >nul

!NSSM_EXE! start ProtoForge
if errorlevel 1 goto :failed

echo.
echo [OK] ProtoForge service installed and started.
echo   Web UI     : http://localhost:%PORT%
echo   Admin pwd  : ProtoForge-Service-Please-Change-Me  ^(set via NSSM AppEnvironmentExtra^)
echo   Logs       : %LOG_DIR%\service-out.log
echo   Uninstall  : scripts\uninstall_service.bat
goto :eof

:failed
echo [ERROR] Service installation failed. See messages above.
exit /b 1
