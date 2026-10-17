@echo off
cd /d "%~dp0"
"%~dp0python_embeded\python.exe" -s "%~dp0start_gpu.py"
pause
