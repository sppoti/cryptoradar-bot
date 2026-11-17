import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot
from bot import TelegramConflictFilter


class TestBotDeploymentAndGracefulShutdown(unittest.IsolatedAsyncioTestCase):
    """Тестирование подавления TelegramConflictError и корректного SIGTERM/SIGINT завершения."""

    def test_telegram_conflict_filter_downgrades_conflict(self):
        """Проверка перехвата TelegramConflictError и даунгрейда до INFO без красных бейджей."""
        log_filter = TelegramConflictFilter()

        # Тест 1: Запись с текстом ошибки TelegramConflictError
        record = logging.LogRecord(
            name="aiogram.dispatcher",
            level=logging.ERROR,
            pathname=__file__,
            lineno=20,
            msg="Failed to fetch updates - %s: %s",
            args=("TelegramConflictError", "Telegram server says - Conflict: terminated by other getUpdates request"),
            exc_info=None,
        )

        result = log_filter.filter(record)
        self.assertTrue(result)
        self.assertEqual(record.levelno, logging.INFO)
        self.assertEqual(record.levelname, "INFO")
        self.assertIn("Облачный перезапуск (Zero-downtime)", record.msg)
        self.assertEqual(record.args, ())

        # Форматирование не должно вызывать исключений
        formatter = logging.Formatter("%(levelname)s: %(message)s")
        formatted = formatter.format(record)
        self.assertIn("INFO: Облачный перезапуск", formatted)

    def test_telegram_conflict_filter_ignores_regular_errors(self):
        """Проверка того, что обычные ошибки (например NetworkError) не затрагиваются фильтром."""
        log_filter = TelegramConflictFilter()

        record = logging.LogRecord(
            name="aiogram.dispatcher",
            level=logging.ERROR,
            pathname=__file__,
            lineno=40,
            msg="Failed to fetch updates - %s: %s",
            args=("NetworkError", "Connection reset by peer"),
            exc_info=None,
        )

        result = log_filter.filter(record)
        self.assertTrue(result)
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertEqual(record.levelname, "ERROR")
        self.assertEqual(record.msg, "Failed to fetch updates - %s: %s")
        self.assertEqual(record.args, ("NetworkError", "Connection reset by peer"))

    async def test_signal_stop_polling_integration(self):
        """Проверка работы stop_polling при получении сигнала завершения."""
        from aiogram import Bot, Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage
        from aiogram.types import User

        test_bot = Bot(token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
        test_bot.me = AsyncMock(return_value=User(id=123, is_bot=True, first_name="TestBot", username="test_bot"))
        test_bot.get_updates = AsyncMock(return_value=[])

        dp = Dispatcher(storage=MemoryStorage())
        stop_event = asyncio.Event()

        def _handle_exit_signal(sig_name: str = ""):
            stop_event.set()
            if dp._running_lock.locked():
                asyncio.create_task(dp.stop_polling())

        # Симулируем отправку SIGTERM через 0.1 секунды после старта polling
        async def delayed_signal():
            await asyncio.sleep(0.1)
            _handle_exit_signal("SIGTERM")

        asyncio.create_task(delayed_signal())

        # Polling должен завершиться чисто без зависаний
        await dp.start_polling(test_bot, handle_signals=False, polling_timeout=1)
        self.assertTrue(stop_event.is_set())
        await test_bot.session.close()


if __name__ == "__main__":
    unittest.main()
