@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\cluster\desktop\start-vision-node.ps1" %*
exit /b %errorlevel%
