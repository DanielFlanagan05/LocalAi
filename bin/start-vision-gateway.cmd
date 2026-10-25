@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\cluster\gateway\start-gateway.ps1" %*
exit /b %errorlevel%
