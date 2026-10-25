@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\cluster\gateway\stop-gateway.ps1" %*
exit /b %errorlevel%
