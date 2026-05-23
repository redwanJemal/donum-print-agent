@echo off
title Donum Print Agent
cd /d "%~dp0"

:loop
echo [%date% %time%] Starting agent...
python agent.py
echo [%date% %time%] Agent stopped. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
