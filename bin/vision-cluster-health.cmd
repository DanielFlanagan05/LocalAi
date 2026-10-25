@echo off
setlocal
"%~dp0..\cluster\gateway\.venv\Scripts\python.exe" "%~dp0..\cluster\scripts\cluster-health.py" %*
exit /b %errorlevel%
