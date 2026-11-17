import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
import database as db
from handlers import user, payments, admin, vip_services
from services import autopilot, vip_channel
import web_server

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TGBot")

async def main():
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("❌ ОШИБКА: Не указан BOT_TOKEN в файле .env!")
        print("\n" + "="*60)
        print("ВНИМАНИЕ! Вы еще не указали токен бота в файле .env.")
        print("1. Откройте в Telegram бота @BotFather и создайте нового бота (/newbot).")
        print("2. Скопируйте полученный токен.")
        print("3. Вставьте его в файл c:\\TG\\.env в поле BOT_TOKEN=")
        print("="*60 + "\n")
        return

    # Инициализация базы данных
    logger.info("Инициализация базы данных SQLite...")
    await db.init_db()

    # Создание экземпляра бота и диспетчера
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутеров в правильном порядке
    dp.include_router(admin.router)
    dp.include_router(payments.router)
    dp.include_router(vip_services.router)
    dp.include_router(user.router)

    # Фоновая задача автопостинга в канал
    autopilot_task = None
    if config.CHANNEL_ID:
        logger.info(f"Запуск автопилота для канала {config.CHANNEL_ID} (каждые {config.AUTOPILOT_INTERVAL_HOURS} ч)...")
        autopilot_task = asyncio.create_task(autopilot.autopilot_loop(bot))
    else:
        logger.info("CHANNEL_ID не указан — автопостинг в канал выключен (бот работает локально).")

    # Фоновая задача проверки истекших подписок в закрытом VIP-канале
    vip_expiry_task = None
    if vip_channel.is_vip_channel_configured():
        logger.info(f"Запуск чекера истекших VIP-подписок для канала {config.VIP_CHANNEL_ID}...")
        vip_expiry_task = asyncio.create_task(vip_channel.vip_expiry_checker_loop(bot))
    else:
        logger.info("VIP_CHANNEL_ID не настроен — используется обратная совместимость со статической ссылкой VIP_LINK.")

    # Запуск TMA Web API сервера рядом с ботом
    web_runner = None
    try:
        web_runner = await web_server.start_web_server(config.WEB_HOST, config.WEB_PORT)
    except Exception as e:
        logger.warning(f"Веб-сервер не запущен в процессе бота (возможно порт занят или запущен отдельно): {e}")

    # Синхронизация Telegram Bot API (команды и WebApp Menu Button)
    if config.WEBAPP_URL and config.WEBAPP_URL.startswith("https://"):
        try:
            import tunnel_manager
            tunnel_manager.configure_telegram_bot(config.BOT_TOKEN, config.WEBAPP_URL)
        except Exception as e:
            logger.warning(f"Не удалось настроить WebApp menu button: {e}")

    try:
        bot_info = await bot.get_me()
        logger.info(f"🚀 Проект запущен: @{bot_info.username} (ID: {bot_info.id})")
        print("\n" + "*"*55)
        print(f"✅ Бот и сервис активны: https://t.me/{bot_info.username}")
        print(f"🌐 TMA WebApp: http://{config.WEB_HOST}:{config.WEB_PORT}")
        print("Для остановки нажмите Ctrl+C")
        print("*"*55 + "\n")
        
        # Удаляем вебхуки и запускаем polling
        await bot.delete_webhook(drop_pending_updates=True)
        allowed_updates = dp.resolve_used_update_types()
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")
    finally:
        if autopilot_task:
            autopilot_task.cancel()
        if vip_expiry_task:
            vip_expiry_task.cancel()
        if web_runner:
            await web_runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
