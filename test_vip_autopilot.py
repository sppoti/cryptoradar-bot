import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import config
import database as db
import keyboards as kb
from handlers import admin, user
from services import vip_autopilot, ai_analytics, scanner

TEST_DB = "test_vip_autopilot_db.db"


def make_mock_callback(user_id: int = 123) -> MagicMock:
    cb = MagicMock()
    cb.from_user.id = user_id
    cb.from_user.username = "admin_user"
    cb.from_user.first_name = "Admin"
    cb.message = MagicMock()
    cb.message.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    cb.bot = AsyncMock()
    return cb


class TestVipAutopilotSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_db = db.DB_PATH
        db.DB_PATH = TEST_DB
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except Exception:
                pass
        await db.init_db()

        self.original_vip_channel_id = config.VIP_CHANNEL_ID
        self.original_channel_id = config.CHANNEL_ID
        self.original_admin_id = config.ADMIN_ID
        self.original_webapp_url = config.WEBAPP_URL

        config.VIP_CHANNEL_ID = -1003961748562
        config.CHANNEL_ID = -1001234567890
        config.ADMIN_ID = 999888
        config.WEBAPP_URL = "https://sppoti.github.io/cryptoradar-tma/"

    async def asyncTearDown(self):
        db.DB_PATH = self.original_db
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except Exception:
                pass
        config.VIP_CHANNEL_ID = self.original_vip_channel_id
        config.CHANNEL_ID = self.original_channel_id
        config.ADMIN_ID = self.original_admin_id
        config.WEBAPP_URL = self.original_webapp_url

    # =========================================================================
    # 1. ТЕСТЫ FEAR & GREED INDEX
    # =========================================================================

    async def test_fng_bar_formatting(self):
        bar_0 = vip_autopilot._get_fng_bar(0)
        self.assertIn("░░░░░░░░░░", bar_0)
        self.assertIn("0%", bar_0)

        bar_50 = vip_autopilot._get_fng_bar(50)
        self.assertIn("█████░░░░░", bar_50)
        self.assertIn("50%", bar_50)

        bar_74 = vip_autopilot._get_fng_bar(74)
        self.assertIn("███████░░░", bar_74)
        self.assertIn("74%", bar_74)

        bar_100 = vip_autopilot._get_fng_bar(100)
        self.assertIn("██████████", bar_100)
        self.assertIn("100%", bar_100)

    async def test_get_fear_and_greed_live_or_mock_success(self):
        """Проверка парсинга успешного ответа Alternative.me."""
        mock_response_data = {
            "name": "Fear and Greed Index",
            "data": [
                {
                    "value": "74",
                    "value_classification": "Greed",
                    "timestamp": "1710000000"
                }
            ]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_response_data)

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            res = await vip_autopilot.get_fear_and_greed()
            self.assertEqual(res["value"], "74")
            self.assertEqual(res["classification"], "Greed")

    async def test_get_fear_and_greed_fallback(self):
        """Проверка расчетного фоллбэка при недоступности API Alternative.me."""
        mock_tickers = [
            {"symbol": "BTCUSDT", "priceChangePercent": "5.5"},
            {"symbol": "ETHUSDT", "priceChangePercent": "4.2"},
            {"symbol": "SOLUSDT", "priceChangePercent": "8.0"}
        ]

        # Эмулируем сбой сетевого запроса к Alternative.me
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("Connection timeout 5s")
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("services.scanner.get_top_market_tickers", AsyncMock(return_value=mock_tickers)):
            res = await vip_autopilot.get_fear_and_greed()
            self.assertIn("value", res)
            self.assertIn("classification", res)
            val_int = int(res["value"])
            self.assertGreaterEqual(val_int, 55)  # Так как рынок растет (+5.9%), должен быть Greed
            self.assertIn(res["classification"], ["Greed", "Extreme Greed"])

    # =========================================================================
    # 2. ТЕСТЫ VIP MORNING BRIEFING
    # =========================================================================

    async def test_publish_vip_morning_briefing_no_channel(self):
        """Если VIP_CHANNEL_ID не задан, публикация отменяется."""
        config.VIP_CHANNEL_ID = ""
        bot = AsyncMock()
        success = await vip_autopilot.publish_vip_morning_briefing(bot)
        self.assertFalse(success)
        bot.send_message.assert_not_called()

    async def test_publish_vip_morning_briefing_success(self):
        """Тест успешного формирования и отправки VIP утреннего брифинга."""
        bot = AsyncMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="cryptoradar_bot"))

        mock_fng = {"value": "72", "classification": "Greed"}
        mock_btc = {
            "status": "success",
            "ticker": "BTC",
            "price_formatted": "$91,450.00",
            "change_24h": 3.45,
            "indicators": {
                "bb_lower": 89200.0,
                "bb_upper": 93500.0,
                "ema_20": 90800.0,
                "ema_50": 88400.0
            }
        }
        mock_eth = {
            "status": "success",
            "ticker": "ETH",
            "price_formatted": "$3,240.50",
            "change_24h": 2.15,
            "indicators": {
                "bb_lower": 3100.0,
                "bb_upper": 3380.0,
                "ema_20": 3200.0,
                "ema_50": 3050.0
            }
        }
        mock_top_tickers = [
            {"symbol": "SOLUSDT", "lastPrice": "215.20", "priceChangePercent": "7.80", "quoteVolume": "850000000"},
            {"symbol": "NEARUSDT", "lastPrice": "6.85", "priceChangePercent": "9.40", "quoteVolume": "320000000"}
        ]

        with patch("services.vip_autopilot.get_fear_and_greed", AsyncMock(return_value=mock_fng)), \
             patch("services.ai_analytics.analyze_asset", AsyncMock(side_effect=[mock_btc, mock_eth])), \
             patch("services.scanner.get_top_market_tickers", AsyncMock(return_value=mock_top_tickers)):

            success = await vip_autopilot.publish_vip_morning_briefing(bot)
            self.assertTrue(success)

            bot.send_photo.assert_called_once()
            call_kwargs = bot.send_photo.call_args.kwargs
            self.assertEqual(call_kwargs["chat_id"], config.VIP_CHANNEL_ID)
            self.assertEqual(call_kwargs["parse_mode"], "HTML")

            msg_caption = call_kwargs["caption"]
            self.assertIn("VIP MORNING BRIEFING", msg_caption)
            self.assertIn("72/100", msg_caption)
            self.assertIn("Жадность", msg_caption)
            self.assertIn("#BTC", msg_caption)

            # Проверка кнопок
            kb_obj = call_kwargs["reply_markup"]
            self.assertIsNotNone(kb_obj)
            btns = [btn for row in kb_obj.inline_keyboard for btn in row]
            self.assertEqual(len(btns), 2)
            self.assertIn("WebApp", btns[0].text)
            self.assertTrue(btns[0].url.startswith("https://"))
            self.assertIn("vip=1", btns[0].url)
            self.assertIn("Открыть в боте", btns[1].text)
            self.assertTrue(btns[1].url.startswith("https://t.me/"))
            self.assertIn("terminal", btns[1].url)

    # =========================================================================
    # 3. ТЕСТЫ VIP TRADE SETUP
    # =========================================================================

    async def test_publish_vip_trade_setup_specific_symbol(self):
        """Тест публикации торгового сигнала по переданному активу."""
        bot = AsyncMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="cryptoradar_bot"))

        mock_setup = {
            "status": "success",
            "symbol": "SOLUSDT",
            "ticker": "SOL",
            "price": 210.0,
            "bias": "Strong Long",
            "probability": 88,
            "risk_reward": "1:3.1",
            "entry_zone": "$208.50 - $210.50",
            "tp1": "$216.00 (+2.86%)",
            "tp1_price": 216.0,
            "tp2": "$222.00 (+5.71%)",
            "tp2_price": 222.0,
            "tp3": "$230.00 (+9.52%)",
            "tp3_price": 230.0,
            "stop_loss": "$204.00 (-2.86%)",
            "stop_loss_price": 204.0,
            "indicators": {
                "rsi_1h": 54.2,
                "bb_bandwidth": 6.8,
                "trend": "bullish",
                "volume_spike_ratio": 2.2,
                "is_volume_spike": True
            }
        }

        with patch("services.ai_analytics.analyze_asset", AsyncMock(return_value=mock_setup)):
            success = await vip_autopilot.publish_vip_trade_setup(bot, symbol="SOL")
            self.assertTrue(success)

            bot.send_photo.assert_called_once()
            call_kwargs = bot.send_photo.call_args.kwargs
            self.assertEqual(call_kwargs["chat_id"], config.VIP_CHANNEL_ID)

            caption = call_kwargs["caption"]
            self.assertIn("VIP TRADE SETUP", caption)
            self.assertIn("#SOL", caption)
            self.assertIn("LONG", caption)
            self.assertIn("1:3.1", caption)

            # Проверка кнопок WebApp и бот
            kb_obj = call_kwargs["reply_markup"]
            btns = [btn for row in kb_obj.inline_keyboard for btn in row]
            self.assertEqual(len(btns), 2)
            self.assertIn("WebApp", btns[0].text)
            self.assertIn("vip=1", btns[0].url)
            self.assertIn("symbol=SOL", btns[0].url)
            self.assertIn("Открыть в боте", btns[1].text)
            self.assertIn("terminal_SOL", btns[1].url)

    async def test_publish_vip_trade_setup_auto_select_best(self):
        """Тест автоматического выбора монеты с наивысшим скорингом."""
        bot = AsyncMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="cryptoradar_bot"))

        def fake_analyze(sym):
            sym_clean = sym.replace("USDT", "")
            prob = 92 if sym_clean == "NEAR" else 75
            bias = "Strong Long" if sym_clean == "NEAR" else "Neutral/Chop"
            return {
                "status": "success",
                "symbol": f"{sym_clean}USDT",
                "ticker": sym_clean,
                "price": 10.0,
                "bias": bias,
                "probability": prob,
                "risk_reward": "1:2.9",
                "entry_zone": "$9.90 - $10.05",
                "tp1": "$10.50 (+5.0%)",
                "tp2": "$11.00 (+10.0%)",
                "tp3": "$11.80 (+18.0%)",
                "stop_loss": "$9.60 (-4.0%)",
                "indicators": {
                    "rsi_1h": 58.0,
                    "bb_bandwidth": 5.0,
                    "trend": "bullish",
                    "volume_spike_ratio": 1.5,
                    "is_volume_spike": False
                }
            }

        with patch("services.ai_analytics.analyze_asset", AsyncMock(side_effect=fake_analyze)):
            success = await vip_autopilot.publish_vip_trade_setup(bot, symbol=None)
            self.assertTrue(success)

            call_kwargs = bot.send_photo.call_args.kwargs
            # Должен быть выбран NEAR, так как у него score максимальный (92 + 10 = 102)
            self.assertIn("VIP TRADE SETUP", call_kwargs["caption"])
            self.assertIn("#NEAR", call_kwargs["caption"])

    # =========================================================================
    # 4. ТЕСТЫ WHALE ORDERFLOW ALERT
    # =========================================================================

    async def test_publish_vip_whale_alert_anomaly_found(self):
        """Тест публикации Whale алерта при обнаружении всплеска объема >= 1.7x."""
        bot = AsyncMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="cryptoradar_bot"))

        # Мокируем тикер и свечи для создания аномалии
        mock_ticker = {"lastPrice": "93500.0", "priceChangePercent": "4.8"}
        mock_klines = [[0, 0, 0, 0, 93000.0 + i * 20, 1000.0] for i in range(25)]
        # Последняя свеча с всплеском объема 2.8x
        mock_klines[-1][5] = 3500.0

        with patch("services.scanner.get_ticker_24hr", AsyncMock(return_value=mock_ticker)), \
             patch("services.ai_analytics.fetch_klines", AsyncMock(return_value=mock_klines)), \
             patch("services.ai_analytics.calculate_volume_spike", return_value={"spike_ratio": 2.8, "is_spike": True}), \
             patch("services.ai_analytics.calculate_rsi_series", return_value=74.5):

            success = await vip_autopilot.publish_vip_whale_alert(bot, force=False)
            self.assertTrue(success)

            bot.send_photo.assert_called_once()
            call_kwargs = bot.send_photo.call_args.kwargs
            self.assertEqual(call_kwargs["chat_id"], config.VIP_CHANNEL_ID)

            caption = call_kwargs["caption"]
            self.assertIn("WHALE RADAR", caption)
            self.assertIn("2.8x", caption)
            self.assertIn("74.5", caption)

            # Проверяем, что алерт записан в БД
            can_post = await db.can_post_alert("BTCUSDT", "VIP_WHALE", cooldown_hours=2)
            self.assertFalse(can_post, "После отправки алерта монета должна быть на кулдауне")

    async def test_publish_vip_whale_alert_force_mode(self):
        """Тест форсированной отправки алерта администратором."""
        bot = AsyncMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="cryptoradar_bot"))

        mock_ticker = {"lastPrice": "205.0", "priceChangePercent": "-1.5"}
        mock_klines = [[0, 0, 0, 0, 205.0, 500.0] for _ in range(25)]

        with patch("services.scanner.get_ticker_24hr", AsyncMock(return_value=mock_ticker)), \
             patch("services.ai_analytics.fetch_klines", AsyncMock(return_value=mock_klines)), \
             patch("services.ai_analytics.calculate_volume_spike", return_value={"spike_ratio": 1.1, "is_spike": False}), \
             patch("services.ai_analytics.calculate_rsi_series", return_value=50.0):

            # force=True должен опубликовать алерт даже без рыночной аномалии
            success = await vip_autopilot.publish_vip_whale_alert(bot, force=True)
            self.assertTrue(success)
            bot.send_photo.assert_called_once()

    # =========================================================================
    # 5. ТЕСТЫ ОБРАБОТЧИКОВ АДМИНКИ (ADMIN CALLBACKS)
    # =========================================================================

    async def test_admin_vip_setup_callback(self):
        cb = make_mock_callback(user_id=config.ADMIN_ID)
        with patch("services.vip_autopilot.publish_vip_trade_setup", AsyncMock(return_value=True)):
            await admin.cb_admin_test_vip_setup(cb)
            cb.answer.assert_called()
            cb.message.answer.assert_called_once()
            ans_text = cb.message.answer.call_args[0][0]
            self.assertIn("VIP Trade Setup успешно опубликован", ans_text)

    async def test_admin_vip_morning_callback(self):
        cb = make_mock_callback(user_id=config.ADMIN_ID)
        with patch("services.vip_autopilot.publish_vip_morning_briefing", AsyncMock(return_value=True)):
            await admin.cb_admin_test_vip_morning(cb)
            cb.answer.assert_called()
            cb.message.answer.assert_called_once()
            ans_text = cb.message.answer.call_args[0][0]
            self.assertIn("VIP Morning Briefing успешно опубликован", ans_text)

    async def test_admin_vip_whale_callback(self):
        cb = make_mock_callback(user_id=config.ADMIN_ID)
        with patch("services.vip_autopilot.publish_vip_whale_alert", AsyncMock(return_value=True)) as mock_whale:
            await admin.cb_admin_test_vip_whale(cb)
            cb.answer.assert_called()
            mock_whale.assert_called_once_with(cb.bot, force=True)
            cb.message.answer.assert_called_once()
            ans_text = cb.message.answer.call_args[0][0]
            self.assertIn("Whale Orderflow Alert успешно опубликован", ans_text)

    async def test_admin_vip_callbacks_denied_for_non_admin(self):
        cb = make_mock_callback(user_id=12345)  # Не админ
        await admin.cb_admin_test_vip_setup(cb)
        cb.answer.assert_called_with("Доступ запрещен.", show_alert=True)
        cb.message.answer.assert_not_called()

    async def test_admin_vip_callbacks_no_channel_id(self):
        config.VIP_CHANNEL_ID = ""
        cb = make_mock_callback(user_id=config.ADMIN_ID)
        await admin.cb_admin_test_vip_setup(cb)
        cb.answer.assert_called_with("⚠️ VIP_CHANNEL_ID не указан!", show_alert=True)
        cb.message.answer.assert_not_called()

    # =========================================================================
    # 6. ТЕСТЫ ИНТЕГРАЦИИ В КЛАВИАТУРЫ
    # =========================================================================

    def test_keyboards_have_test_buttons(self):
        panel_kb = kb.get_admin_panel()
        callbacks = [btn.callback_data for row in panel_kb.inline_keyboard for btn in row]
        self.assertIn("admin_test_vip_setup", callbacks)
        self.assertIn("admin_test_vip_morning", callbacks)
        self.assertIn("admin_test_vip_whale", callbacks)

        vip_kb = kb.get_admin_vip_channel_keyboard()
        vip_callbacks = [btn.callback_data for row in vip_kb.inline_keyboard for btn in row]
        self.assertIn("admin_test_vip_setup", vip_callbacks)
        self.assertIn("admin_test_vip_morning", vip_callbacks)
        self.assertIn("admin_test_vip_whale", vip_callbacks)

    # =========================================================================
    # 7. ТЕСТ ИНТЕГРАЦИИ В AUTOPILOT LOOP
    # =========================================================================

    async def test_autopilot_loop_vip_ticks(self):
        """Проверка вызова функций VIP автопилота при итерациях цикла."""
        from services import autopilot

        bot = AsyncMock()

        # Мокируем функции vip_autopilot и asyncio.sleep
        with patch("services.vip_autopilot.publish_vip_whale_alert", AsyncMock(return_value=True)) as mock_whale, \
             patch("services.vip_autopilot.publish_vip_trade_setup", AsyncMock(return_value=True)) as mock_setup, \
             patch("services.vip_autopilot.publish_vip_morning_briefing", AsyncMock(return_value=True)) as mock_briefing, \
             patch("services.autopilot.publish_flash_alert", AsyncMock(return_value=True)), \
             patch("services.news.publish_latest_news", AsyncMock(return_value=True)), \
             patch("services.autopilot.publish_market_update", AsyncMock(return_value=True)):

            # Останавливаем цикл через CancelledError на втором тике
            sleep_count = 0
            async def fake_sleep(duration):
                nonlocal sleep_count
                sleep_count += 1
                if sleep_count > 2:
                    raise asyncio.CancelledError()

            with patch("asyncio.sleep", side_effect=fake_sleep):
                await autopilot.autopilot_loop(bot)

            # На нулевом тике (tick=0): 0 % 2 == 0, 0 % 16 == 0, 0 % 96 == 0
            mock_whale.assert_called()
            mock_setup.assert_called()
            mock_briefing.assert_called()

    # =========================================================================
    # 6. ТЕСТЫ DEEP LINKS (TERMINAL & ANALYZE) И ССЫЛОК VIP КАНАЛА
    # =========================================================================

    def test_build_channel_links_structure(self):
        """Проверка добавления vip=1 и deep links в build_channel_links."""
        links_sol = vip_autopilot.build_channel_links("test_bot", coin_symbol="SOL")
        self.assertIn("vip=1", links_sol["direct_vip_url"])
        self.assertIn("symbol=SOL", links_sol["direct_vip_url"])
        self.assertEqual(links_sol["webapp"], links_sol["direct_vip_url"])
        self.assertIn("start=terminal_SOL", links_sol["bot_terminal_url"])
        self.assertIn("start=analyze_SOL", links_sol["bot_analyze_url"])

        links_general = vip_autopilot.build_channel_links("test_bot", coin_symbol=None)
        self.assertIn("vip=1", links_general["direct_vip_url"])
        self.assertNotIn("symbol=", links_general["direct_vip_url"])
        self.assertIn("start=terminal", links_general["bot_terminal_url"])
        self.assertIn("start=analyze", links_general["bot_analyze_url"])

    async def test_deep_link_terminal_vip(self):
        """Deep link /start terminal_SOL для VIP пользователя."""
        msg = MagicMock()
        msg.from_user.id = 999888  # ADMIN_ID -> VIP
        msg.from_user.username = "admin_vip"
        msg.from_user.first_name = "VIP Admin"
        msg.text = "/start terminal_SOL"
        msg.caption = None
        msg.answer = AsyncMock()

        state = MagicMock()
        state.clear = AsyncMock()

        await user.cmd_start(msg, state)

        msg.answer.assert_called_once()
        args, kwargs = msg.answer.call_args
        sent_text = args[0]
        self.assertIn("Торговый терминал CryptoRadar PRO", sent_text)
        self.assertIn("SOL/USDT", sent_text)
        self.assertIn("PRO VIP Активен", sent_text)

        markup = kwargs.get("reply_markup")
        self.assertIsNotNone(markup)
        launch_btn = markup.inline_keyboard[0][0]
        self.assertIn("Запустить терминал (SOL)", launch_btn.text)
        self.assertIsNotNone(launch_btn.web_app)
        self.assertIn("vip=1", launch_btn.web_app.url)
        self.assertIn("symbol=SOL", launch_btn.web_app.url)
        self.assertIn("user_id=999888", launch_btn.web_app.url)

    async def test_deep_link_terminal_free(self):
        """Deep link /start terminal_ETH для бесплатного пользователя."""
        free_user_id = 112233
        msg = MagicMock()
        msg.from_user.id = free_user_id
        msg.from_user.username = "free_user"
        msg.from_user.first_name = "Free Trader"
        msg.text = "/start terminal_ETH"
        msg.caption = None
        msg.answer = AsyncMock()

        state = MagicMock()
        state.clear = AsyncMock()

        await user.cmd_start(msg, state)

        msg.answer.assert_called_once()
        args, kwargs = msg.answer.call_args
        sent_text = args[0]
        self.assertIn("Базовый доступ (Free)", sent_text)
        self.assertIn("ETH/USDT", sent_text)

        markup = kwargs.get("reply_markup")
        self.assertIsNotNone(markup)
        launch_btn = markup.inline_keyboard[0][0]
        self.assertIn("vip=0", launch_btn.web_app.url)
        self.assertIn("symbol=ETH", launch_btn.web_app.url)

    async def test_deep_link_analyze_vip(self):
        """Deep link /start analyze_SOL для VIP пользователя."""
        vip_user_id = 999888  # Admin -> VIP
        msg = MagicMock()
        msg.from_user.id = vip_user_id
        msg.from_user.username = "vip_trader"
        msg.from_user.first_name = "VIP"
        msg.text = "/start analyze_SOL"
        msg.caption = None
        msg.answer = AsyncMock()

        state = MagicMock()
        state.clear = AsyncMock()

        mock_report = "📊 <b>Экспресс-анализ: SOL / USDT</b>\nРынок в норме."
        with patch("services.ai_analytics.format_analysis_report", AsyncMock(return_value=mock_report)) as mock_fmt:
            await user.cmd_start(msg, state)
            mock_fmt.assert_called_once_with("SOL")
            msg.answer.assert_called_once()
            args, kwargs = msg.answer.call_args
            self.assertIn("Экспресс-анализ: SOL / USDT", args[0])

    async def test_deep_link_analyze_free(self):
        """Deep link /start analyze_SOL для бесплатного пользователя (показ тизера)."""
        free_user_id = 554433
        msg = MagicMock()
        msg.from_user.id = free_user_id
        msg.from_user.username = "free_user2"
        msg.from_user.first_name = "Free"
        msg.text = "/start analyze_SOL"
        msg.caption = None
        msg.answer = AsyncMock()

        state = MagicMock()
        state.clear = AsyncMock()

        await user.cmd_start(msg, state)

        msg.answer.assert_called_once()
        args, kwargs = msg.answer.call_args
        self.assertIn("Инструмент «Экспресс-анализ монеты» доступен только для VIP-участников!", args[0])


if __name__ == "__main__":
    unittest.main()
