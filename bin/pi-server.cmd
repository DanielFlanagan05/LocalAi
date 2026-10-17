@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\launchers\start-pi-web-ui.ps1" -WorkspacePath "%CD%"
exit /b %errorlevel%
