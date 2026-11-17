@echo off
chcp 65001 > nul
title Генерация видео через Gemini Omni Flash
cd /d "%~dp0"

echo ==========================================================
echo    Генерация ИИ-видео через Gemini Omni 1.1 Flash (Full HD)
echo ==========================================================
echo.

python generate_gemini_video.py

echo.
pause
