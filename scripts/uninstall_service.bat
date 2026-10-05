@echo off
REM ProtoForge Windows Service uninstaller (v1.5.0)
REM Stops and removes the ProtoForge service created by install_service.bat.
REM Run as Administrator.

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator privileges required.
    exit /b 1
)

set NSSM_EXE=nssm
where nssm >nul 2>&1
if errorlevel 1 (
    if exist "tools\nssm.exe" (
        set NSSM_EXE=%~dp0..\tools\nssm.exe
    )
)

echo Stopping ProtoForge service...
%NSSM_EXE% stop ProtoForge >nul 2>&1

echo Removing ProtoForge service...
%NSSM_EXE% remove ProtoForge confirm >nul 2>&1

sc query ProtoForge >nul 2>&1
if errorlevel 1 (
    echo [OK] ProtoForge service removed.
) else (
    echo [WARN] Service may still exist. Try: sc delete ProtoForge
)
