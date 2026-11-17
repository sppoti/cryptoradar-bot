@echo off
chcp 65001 > nul
title CryptoRadar PRO — Автономный 1-Click запуск
cd /d "%~dp0"

echo ====================================================================
echo            🚀 CRYPTORADAR PRO — 1-CLICK SAAS LAUNCHER
echo ====================================================================
echo  - Локальный WebApp API сервер (порт 8080)
echo  - Автоматический публичный HTTPS туннель (Cloudflare / Fallback)
echo  - Авто-регистрация WebApp Menu Button ("🚀 Терминал PRO") в Telegram
echo  - Авто-регистрация команд бота (/start, /signals, /vip, /partner)
echo  - Запуск Telegram бота с AI-радаром и автопилотом
echo ====================================================================
echo.

python start_saas.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ⚠️ Запуск завершился с кодом %ERRORLEVEL%. Попробуйте запустить обычный режим:
    echo python bot.py
)

echo.
pause
