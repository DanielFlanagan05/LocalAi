@echo off
cd /d "%~dp0"
python_embeded\python.exe -s manage_comfy.py start
if errorlevel 1 pause
