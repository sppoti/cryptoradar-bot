import asyncio
import logging
import signal
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


class TelegramConflictFilter(logging.Filter):
    """
    Фильтр для подавления ложных тревог TelegramConflictError
    во время бесшовного перезапуска контейнеров на Render (Zero-Downtime Deployment).
    Понижает уровень записи с ERROR до INFO.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "TelegramConflictError" in msg or "Conflict: terminated by other getUpdates" in msg:
            # Downgrade from ERROR to INFO so it doesn't alarm the user with red error badges on Render
            record.levelno = logging.INFO
            record.levelname = "INFO"
            record.msg = "Облачный перезапуск (Zero-downtime): ожидание завершения предыдущего контейнера..."
            record.args = ()
        return True


logging.getLogger("aiogram.dispatcher").addFilter(TelegramConflictFilter())

async def main():
    # 1. Запуск TMA Web API сервера в первую очередь (для прохождения Health Check на хостинге/Render)
    web_runner = None
    try:
        web_runner = await web_server.start_web_server(config.WEB_HOST, config.WEB_PORT)
    except Exception as e:
        logger.warning(f"Веб-сервер не запущен в процессе бота: {e}")

    # 2. Проверка BOT_TOKEN
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("❌ ОШИБКА: Не указан BOT_TOKEN в переменных окружения!")
        print("\n" + "="*60)
        print("ВНИМАНИЕ! Не указан токен бота.")
        print("Веб-сервер запущен для Health Check. Укажите BOT_TOKEN в настройках Environment.")
        print("="*60 + "\n")
        # Удерживаем процесс живым для Render
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            if web_runner:
                await web_runner.cleanup()
        return

    # 3. Инициализация базы данных
    logger.info("Инициализация базы данных SQLite...")
    await db.init_db()

    # 4. Создание экземпляра бота и диспетчера
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
        
        # Удаляем вебхуки (сохраняя накопившиеся обновления) и запускаем polling
        await bot.delete_webhook(drop_pending_updates=False)
        allowed_updates = dp.resolve_used_update_types()

        # Регистрация обработчиков сигналов для корректного завершения (Render Zero-Downtime)
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _handle_exit_signal(sig_name: str = ""):
            logger.info(f"Получен сигнал {sig_name}. Плавная остановка polling (Render Zero-Downtime)...")
            stop_event.set()
            if dp._running_lock.locked():
                asyncio.create_task(dp.stop_polling())

        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, _handle_exit_signal, sig.name)
                except (NotImplementedError, ValueError):
                    try:
                        signal.signal(
                            sig,
                            lambda s, f: _handle_exit_signal(
                                signal.Signals(s).name if hasattr(signal, "Signals") else str(s)
                            ),
                        )
                    except (ValueError, AttributeError):
                        pass
        
        # Устойчивый цикл polling
        while not stop_event.is_set():
            try:
                await dp.start_polling(
                    bot,
                    allowed_updates=allowed_updates,
                    handle_signals=False,
                )
                break
            except Exception as poll_err:
                if stop_event.is_set():
                    break
                logger.warning(f"Ошибка polling: {poll_err}. Переподключение через 10 сек...")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=10)
                    break
                except asyncio.TimeoutError:
                    pass
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")
    finally:
        if "loop" in locals() and loop is not None:
            for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
                if sig is not None:
                    try:
                        loop.remove_signal_handler(sig)
                    except (NotImplementedError, ValueError, RuntimeError):
                        pass
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
