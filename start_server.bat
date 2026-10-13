@echo off
title IoT Fleet Platform Server
cd /d "%~dp0"
echo ==================================================
echo   Starting IoT Fleet Platform Local Server
echo ==================================================
echo.
python run_server.py
pause
