@echo off
REM ============================================================
REM ProtoForge auto-start installer (Windows)
REM Creates a VBS in the current user's Startup folder so that
REM ProtoForge starts automatically (hidden window) at logon.
REM Uninstall: delete ProtoForge_AutoStart.vbs from the Startup folder.
REM NOTE: keep all lines ASCII-only (parsed under legacy codepage).
REM ============================================================

title ProtoForge Auto-Start Installer

REM Move to project root (this script lives in scripts/)
cd /d "%~dp0.."

if not exist "quickstart.bat" (
    echo [ERROR] quickstart.bat not found in project root.
    pause
    exit /b 1
)

echo Installing ProtoForge auto-start ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=[Environment]::GetFolderPath('Startup')+'\ProtoForge_AutoStart.vbs'; $proj=(Get-Location).Path; $t=\"' ProtoForge boot auto-start: run quickstart.bat in a hidden window`r`nSet sh = CreateObject(`\"WScript.Shell`\")`r`nsh.CurrentDirectory = `\"$proj`\"`r`nsh.Run `\"cmd /c quickstart.bat >> data\autostart.log 2>&1`\", 0, False\"; [IO.File]::WriteAllText($p,$t,[Text.Encoding]::Unicode); Write-Host ('Installed: ' + $p)"

if errorlevel 1 (
    echo [ERROR] Failed to write the Startup VBS file.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   ProtoForge will now start automatically at logon.
echo.
echo   - Data (devices, scenarios, templates) is stored in
echo     data\protoforge.db and survives restarts.
echo   - Startup log: data\autostart.log
echo   - Web UI:      http://localhost:8000  (admin / admin)
echo   - Uninstall:   delete ProtoForge_AutoStart.vbs in the
echo                  Startup folder (Win+R: shell:startup)
echo ============================================================
echo.
pause
