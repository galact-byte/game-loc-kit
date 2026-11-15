@echo off
chcp 65001 >nul 2>&1
title game-loc-kit Progress
python "%~dp0launch.py" %*
if errorlevel 1 pause
