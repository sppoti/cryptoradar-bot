import asyncio
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
import database as db
from handlers import user, payments, admin, vip_services
from services import autopilot, vip_channel
import web_server
import tunnel_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SaaS-Starter")

async def run_saas():
    print("\n" + "="*65)
    print("🚀 CRYPTORADAR PRO — ЗАПУСК ПОЛНОЙ АВТОНОМНОЙ SAAS-ИНФРАСТРУКТУРЫ")
    print("="*65)

    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("❌ ОШИБКА: Не указан BOT_TOKEN в файле .env!")
        return

    # 1. Инициализация базы данных
    logger.info("📦 Инициализация базы данных SQLite...")
    await db.init_db()

    # 2. Запуск локального Web API & WebApp сервера (aiohttp)
    host = config.WEB_HOST or "0.0.0.0"
    port = config.WEB_PORT or 8080
    logger.info(f"🌐 Запуск локального сервера WebApp на http://{host}:{port}...")
    web_runner = await web_server.start_web_server(host, port)
    logger.info(f"✅ Локальный сервер запущен на порту {port}.")

    # 3. Проверка или запуск публичного HTTPS URL
    public_url = None
    tunnel = None
    if config.WEBAPP_URL and "github.io" in config.WEBAPP_URL:
        public_url = config.WEBAPP_URL
        logger.info(f"🌐 Используется постоянный хостинг GitHub Pages: {public_url}")
    else:
        # Запуск публичного HTTPS туннеля (Cloudflare / Tunnelmole)
        tunnel = tunnel_manager.TunnelManager(port=port, host="127.0.0.1")
        try:
            public_url = tunnel.start_tunnel()
        except Exception as e:
            logger.error(f"❌ Не удалось поднять внешний HTTPS туннель: {e}")
            public_url = f"http://127.0.0.1:{port}"

    # 4. Автоматическая синхронизация .env и config
    config.WEBAPP_URL = public_url
    if "github.io" not in config.WEBAPP_URL:
        tunnel_manager.update_env_file(public_url, web_host=host, web_port=port)

    # 5. Автоматическая настройка бота через Telegram Bot API
    if public_url.startswith("https://"):
        logger.info(f"⚙️ Регистрация WebApp URL в Telegram Bot API: {public_url}")
        api_res = tunnel_manager.configure_telegram_bot(config.BOT_TOKEN, public_url)
        menu_ok = api_res.get("setChatMenuButton", {}).get("ok", False)
        cmds_ok = api_res.get("setMyCommands", {}).get("ok", False)
        if menu_ok and cmds_ok:
            logger.info("🎉 Bot API синхронизирован: кнопка меню и команды зарегистрированы!")
    else:
        logger.warning("⚠️ Публичный HTTPS URL не получен, регистрация WebApp кнопки пропущена.")

    # 6. Запуск Telegram бота
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(admin.router)
    dp.include_router(payments.router)
    dp.include_router(vip_services.router)
    dp.include_router(user.router)

    autopilot_task = None
    if config.CHANNEL_ID:
        logger.info(f"📢 Запуск автопостинга в канал {config.CHANNEL_ID} (каждые {config.AUTOPILOT_INTERVAL_HOURS} ч)...")
        autopilot_task = asyncio.create_task(autopilot.autopilot_loop(bot))

    vip_expiry_task = None
    if vip_channel.is_vip_channel_configured():
        logger.info(f"Запуск чекера истекших VIP-подписок для канала {config.VIP_CHANNEL_ID}...")
        vip_expiry_task = asyncio.create_task(vip_channel.vip_expiry_checker_loop(bot))

    try:
        bot_info = await bot.get_me()
        print("\n" + "*"*65)
        print(f"🤖 Telegram Бот:         https://t.me/{bot_info.username} (@{bot_info.username})")
        print(f"🌍 Публичный WebApp:     {public_url}")
        print(f"💻 Локальный WebApp:     http://localhost:{port}")
        print(f"🚀 Меню-кнопка в чате:   '🚀 Терминал PRO' -> {public_url}")
        print(f"📋 Официальные команды:  /start, /signals, /vip, /partner, /help")
        print(f"🛡️ Режим работы:         1-Click Автопилот (PRO)")
        print("Для остановки нажмите Ctrl+C")
        print("*"*65 + "\n")

        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")
    finally:
        logger.info("Остановка процессов...")
        if autopilot_task:
            autopilot_task.cancel()
        if vip_expiry_task:
            vip_expiry_task.cancel()
        if web_runner:
            await web_runner.cleanup()
        if tunnel:
            tunnel.stop_tunnel()
        await bot.session.close()
        logger.info("Все сервисы успешно остановлены.")

if __name__ == "__main__":
    try:
        asyncio.run(run_saas())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Завершение работы по запросу пользователя.")
