@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0show-pi-web-ui-token.ps1"
endlocal
