@echo off
rem Analyses songs for the LED lights as the Pi asks for them. Leave this window open while music plays.
cd /d "%~dp0"
.venv\Scripts\python.exe analyze.py watch
pause
