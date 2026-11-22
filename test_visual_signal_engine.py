"""
test_visual_signal_engine.py
Автоматизированный комплексный тест для Task 11: Visual Signal Engine Integration
в VIP Autopilot, боте (handlers/vip_services.py) и клавиатурах (keyboards.py).
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import FSInputFile, Message, CallbackQuery, User, Chat

import config
import database as db
import keyboards as kb
from services import canva_service
from services import vip_autopilot
from handlers import vip_services


class TestVisualSignalEngine(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Настройка in-memory или тестовой БД
        self.test_db = "test_visual_signal.db"
        config.DB_NAME = self.test_db
        db.DB_NAME = self.test_db
        await db.init_db()

        self.user_vip = 111222333
        self.user_free = 444555666
        # Выдаем VIP подписку тестовому пользователю
        await db.add_subscription_days(self.user_vip, 30)

    async def asyncTearDown(self):
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_keyboards_include_signal_card_buttons(self):
        """Проверка наличия кнопки '🖼 Карточка сигнала' в клавиатурах анализа и прогноза."""
        sym = "BTCUSDT"

        # 1. Клавиатура экспресс-анализа
        analysis_kb = kb.get_analysis_result_keyboard(sym)
        cbs_analysis = [b.callback_data for row in analysis_kb.inline_keyboard for b in row if b.callback_data]
        self.assertIn(f"card_{sym}", cbs_analysis, "Кнопка card_{symbol} отсутствует в get_analysis_result_keyboard")
        self.assertIn(f"ai_forecast_{sym}", cbs_analysis)

        # 2. Клавиатура AI-прогноза
        forecast_kb = kb.get_ai_forecast_keyboard(sym)
        cbs_forecast = [b.callback_data for row in forecast_kb.inline_keyboard for b in row if b.callback_data]
        self.assertIn(f"card_{sym}", cbs_forecast, "Кнопка card_{symbol} отсутствует в get_ai_forecast_keyboard")

        # 3. Выделенная клавиатура карточки сигнала
        card_kb = kb.get_signal_card_keyboard(sym)
        cbs_card = [b.callback_data for row in card_kb.inline_keyboard for b in row if b.callback_data]
        self.assertIn(f"card_{sym}", cbs_card)
        self.assertIn(f"ai_forecast_{sym}", cbs_card)
        self.assertIn(f"analyze_{sym}", cbs_card)

    def test_canva_service_dict_rendering(self):
        """Проверка рендеринга карточки при передаче словаря от ai_analytics.analyze_asset."""
        mock_asset_data = {
            "status": "success",
            "symbol": "SOLUSDT",
            "ticker": "SOL",
            "price": 215.50,
            "bias": "Scalp Long",
            "probability": 92,
            "risk_reward": "1:3.2",
            "entry_zone": "$214.00 - $215.50",
            "tp1_price": 222.0,
            "tp2_price": 230.0,
            "stop_loss_price": 210.0,
            "summary": "Отработка локальной перепроданности от EMA-50",
            "indicators": {
                "rsi_1h": 27.4,
                "bb_bandwidth": 3.8,
                "trend": "bullish"
            }
        }
        test_out = "static/canva_renders/test_sol_signal_card.png"
        res_path = canva_service.render_local_signal_card(mock_asset_data, output_filename=test_out)
        self.assertTrue(os.path.exists(res_path))
        self.assertGreater(os.path.getsize(res_path), 10_000)

    @patch("services.vip_autopilot.ai_analytics.analyze_asset")
    async def test_publish_vip_trade_setup_sends_photo(self, mock_analyze):
        """Sunny Day: publish_vip_trade_setup генерирует карточку и отправляет photo с FSInputFile."""
        mock_bot = AsyncMock()
        mock_bot_info = MagicMock()
        mock_bot_info.username = "test_radar_bot"
        mock_bot.get_me.return_value = mock_bot_info
        mock_bot.send_photo.return_value = MagicMock(message_id=101)

        mock_analyze.return_value = {
            "status": "success",
            "symbol": "BTCUSDT",
            "ticker": "BTC",
            "price": 91200.0,
            "price_formatted": "$91,200",
            "bias": "Strong Long",
            "probability": 88,
            "risk_reward": "1:2.8",
            "entry_zone": "$90,800 - $91,200",
            "tp1": "$92,500 (+1.4%)",
            "tp1_price": 92500.0,
            "tp2": "$94,200 (+3.3%)",
            "tp2_price": 94200.0,
            "tp3": "$97,000 (+6.3%)",
            "stop_loss": "$89,600 (-1.8%)",
            "stop_loss_price": 89600.0,
            "indicators": {
                "rsi_1h": 29.1,
                "bb_bandwidth": 3.2,
                "trend": "bullish",
                "volume_spike_ratio": 1.9,
                "is_volume_spike": True
            }
        }

        with patch.object(config, "VIP_CHANNEL_ID", "-1003961748562"):
            success = await vip_autopilot.publish_vip_trade_setup(mock_bot, symbol="BTCUSDT")
            self.assertTrue(success)

            # Проверяем, что send_photo был вызван
            mock_bot.send_photo.assert_called_once()
            call_kwargs = mock_bot.send_photo.call_args.kwargs
            self.assertEqual(call_kwargs["chat_id"], "-1003961748562")
            self.assertIsInstance(call_kwargs["photo"], FSInputFile)
            self.assertIn("VIP TRADE SETUP", call_kwargs["caption"])
            self.assertIn("BTC", call_kwargs["caption"])
            self.assertEqual(call_kwargs["parse_mode"], "HTML")
            # send_message не должен вызываться в случае успеха
            mock_bot.send_message.assert_not_called()

    @patch("services.vip_autopilot.ai_analytics.analyze_asset")
    async def test_publish_vip_trade_setup_fallback_to_text(self, mock_analyze):
        """Rainy Day: если send_photo падает с ошибкой, происходит мягкий fallback на send_message."""
        mock_bot = AsyncMock()
        mock_bot_info = MagicMock()
        mock_bot_info.username = "test_radar_bot"
        mock_bot.get_me.return_value = mock_bot_info
        # Моделируем ошибку отправки фото в Telegram
        mock_bot.send_photo.side_effect = Exception("TelegramBadRequest: Photo invalid or too large")
        mock_bot.send_message.return_value = MagicMock(message_id=102)

        mock_analyze.return_value = {
            "status": "success",
            "symbol": "ETHUSDT",
            "ticker": "ETH",
            "price": 3150.0,
            "price_formatted": "$3,150",
            "bias": "Scalp Short",
            "probability": 80,
            "risk_reward": "1:2.4",
            "entry_zone": "$3,140 - $3,160",
            "tp1": "$3,080 (-2.2%)",
            "tp1_price": 3080.0,
            "tp2": "$3,020 (-4.1%)",
            "tp2_price": 3020.0,
            "stop_loss": "$3,210 (+1.9%)",
            "stop_loss_price": 3210.0,
            "indicators": {
                "rsi_1h": 74.2,
                "bb_bandwidth": 4.1,
                "trend": "bearish",
                "volume_spike_ratio": 1.6,
                "is_volume_spike": False
            }
        }

        with patch.object(config, "VIP_CHANNEL_ID", "-1003961748562"):
            success = await vip_autopilot.publish_vip_trade_setup(mock_bot, symbol="ETHUSDT")
            self.assertTrue(success)

            # Проверяем, что была попытка send_photo, а затем вызов send_message (fallback)
            mock_bot.send_photo.assert_called_once()
            mock_bot.send_message.assert_called_once()
            call_kwargs = mock_bot.send_message.call_args.kwargs
            self.assertEqual(call_kwargs["chat_id"], "-1003961748562")
            self.assertIn("VIP TRADE SETUP", call_kwargs["text"])

    async def test_card_callback_handler_vip_and_non_vip(self):
        """Проверка работы callback card_{symbol}: тизер для free-юзера и отправка фото для VIP."""
        # 1. Non-VIP User (Rainy Day)
        cb_free = AsyncMock()
        cb_free.from_user = User(id=self.user_free, is_bot=False, first_name="FreeUser")
        cb_free.data = "card_BTCUSDT"
        cb_free.message = AsyncMock()
        cb_free.answer = AsyncMock()

        await vip_services.cb_signal_card(cb_free)
        cb_free.message.edit_text.assert_called_once()
        args = cb_free.message.edit_text.call_args[0]
        self.assertIn("Экспресс-анализ монеты", args[0])

        # 2. VIP User (Sunny Day)
        cb_vip = AsyncMock()
        cb_vip.from_user = User(id=self.user_vip, is_bot=False, first_name="VipUser")
        cb_vip.data = "card_BTCUSDT"
        cb_vip.answer = AsyncMock()
        loading_msg = AsyncMock()
        cb_vip.message = AsyncMock()
        cb_vip.message.answer = AsyncMock(return_value=loading_msg)
        cb_vip.message.answer_photo = AsyncMock()

        with patch("handlers.vip_services.ai_analytics.analyze_asset") as mock_an:
            mock_an.return_value = {
                "status": "success",
                "symbol": "BTCUSDT",
                "ticker": "BTC",
                "price": 91500.0,
                "bias": "Strong Long",
                "probability": 94,
                "risk_reward": "1:3.0",
                "entry_zone": "$91,000 - $91,500",
                "tp1": "$93,000 (+1.6%)",
                "tp1_price": 93000.0,
                "tp2": "$95,500 (+4.3%)",
                "tp2_price": 95500.0,
                "stop_loss": "$89,800 (-1.8%)",
                "stop_loss_price": 89800.0,
                "indicators": {"rsi_1h": 26.5}
            }

            await vip_services.cb_signal_card(cb_vip)

            # Проверяем отправку фото
            cb_vip.message.answer_photo.assert_called_once()
            call_kw = cb_vip.message.answer_photo.call_args.kwargs
            self.assertIsInstance(call_kw["photo"], FSInputFile)
            self.assertIn("VIP SIGNAL CARD", call_kw["caption"])
            self.assertIn("BTC", call_kw["caption"])

    async def test_card_command_handler(self):
        """Проверка команды /card BTC и /card без аргументов."""
        # 1. /card BTC (Sunny Day для VIP)
        msg_vip = AsyncMock()
        msg_vip.from_user = User(id=self.user_vip, is_bot=False, first_name="VipUser")
        msg_vip.text = "/card BTC"
        loading_msg = AsyncMock()
        msg_vip.answer = AsyncMock(return_value=loading_msg)
        msg_vip.answer_photo = AsyncMock()
        state = AsyncMock()

        with patch("handlers.vip_services.ai_analytics.analyze_asset") as mock_an:
            mock_an.return_value = {
                "status": "success",
                "symbol": "BTCUSDT",
                "ticker": "BTC",
                "price": 91500.0,
                "bias": "Strong Long",
                "probability": 94,
                "risk_reward": "1:3.0",
                "entry_zone": "$91,000 - $91,500",
                "tp1": "$93,000 (+1.6%)",
                "tp1_price": 93000.0,
                "tp2": "$95,500 (+4.3%)",
                "tp2_price": 95500.0,
                "stop_loss": "$89,800 (-1.8%)",
                "stop_loss_price": 89800.0,
                "indicators": {"rsi_1h": 26.5}
            }

            await vip_services.cmd_signal_card(msg_vip, state)
            msg_vip.answer_photo.assert_called_once()
            call_kw = msg_vip.answer_photo.call_args.kwargs
            self.assertIsInstance(call_kw["photo"], FSInputFile)
            self.assertIn("VIP SIGNAL CARD", call_kw["caption"])

        # 2. /card без аргументов (запрос тикера)
        msg_no_args = AsyncMock()
        msg_no_args.from_user = User(id=self.user_vip, is_bot=False, first_name="VipUser")
        msg_no_args.text = "/card"
        msg_no_args.answer = AsyncMock()

        await vip_services.cmd_signal_card(msg_no_args, state)
        msg_no_args.answer.assert_called_once()
        text_arg = msg_no_args.answer.call_args[0][0]
        self.assertIn("Генерация визуальной карточки сигнала", text_arg)


if __name__ == "__main__":
    unittest.main()
