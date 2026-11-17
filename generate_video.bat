@echo off
chcp 65001 > nul
title Генератор рекламных Reels / Shorts
cd /d "%~dp0"

echo ====================================================
echo    Генерация рекламного ролика (Reels / Shorts)
echo ====================================================
echo.

python generate_reel.py

echo.
echo Ролик сохранен в папку: %~dp0videos\
pause
