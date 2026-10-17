@echo off
setlocal
cd /d "%~dp0..\..\apps\ComfyUI"
python_embeded\python.exe -s start_gpu.py
endlocal
