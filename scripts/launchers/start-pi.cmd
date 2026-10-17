@echo off
setlocal
set "LOCALAI_ROOT=C:\Users\danfl\dev\LocalAI"
set "PI_CODING_AGENT_DIR=%LOCALAI_ROOT%\config\pi"
set "PI_CODING_AGENT_SESSION_DIR=%LOCALAI_ROOT%\config\pi\sessions"
set "PI_COMPUTER_USE_WINDOWS_HELPER_PATH=%LOCALAI_ROOT%\config\pi\helpers\pi-computer-use\windows-bridge.exe"
set "PATH=%LOCALAI_ROOT%\apps\PiHarness\runtime\node-v22.19.0-win-x64;%PATH%"
call "%LOCALAI_ROOT%\apps\PiHarness\runtime\pi-1.2.0\pi.cmd" %*
endlocal
