@echo off
rem Opens the LED lights editor in the browser. Leave this window open while you use it.
cd /d "%~dp0"
.venv\Scripts\python.exe editor.py
pause
