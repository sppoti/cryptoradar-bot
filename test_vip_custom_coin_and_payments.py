import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import config
import database as db
import keyboards as kb
from services import scanner
from handlers import vip_services, payments, user
from aiogram import Dispatcher, Bot
from aiogram.types import Update, Message, User, Chat
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey


class TestTariffsAndPaymentDetails(unittest.IsolatedAsyncioTestCase):
    """Проверка R2 и R3: тарифы и реквизиты оплаты."""

    def test_tariff_1m_price(self):
        """Стоимость тарифа sub_1m установлена в 150 рублей."""
        self.assertIn("sub_1m", config.TARIFFS)
        self.assertEqual(config.TARIFFS["sub_1m"]["rub_price"], 150)

    def test_keyboards_display_150_rub(self):
        """Тексты кнопок тарифов и оплаты отображают только Stars без СБП/рублей."""
        tariffs_kb = kb.get_tariffs_keyboard()
        tariff_texts = [btn.text for row in tariffs_kb.inline_keyboard for btn in row]
        self.assertTrue(any("150 ⭐" in t for t in tariff_texts), f"150 ⭐ not found in {tariff_texts}")
        self.assertFalse(any("₽" in t for t in tariff_texts), f"Found ruble in {tariff_texts}")

        pay_kb = kb.get_payment_methods("sub_1m")
        pay_texts = [btn.text for row in pay_kb.inline_keyboard for btn in row]
        self.assertTrue(any("150 ⭐" in t for t in pay_texts), f"150 ⭐ not found in {pay_texts}")
        self.assertFalse(any("₽" in t for t in pay_texts), f"Found ruble in {pay_texts}")

    def test_teaser_displays_150_rub(self):
        """Тизер подписки отображает стоимость в Stars."""
        teaser = vip_services.get_vip_teaser_text()
        self.assertIn("150 ⭐", teaser)
        self.assertNotIn("500 ₽", teaser)

    def test_manual_payment_details_content(self):
        """Реквизиты содержат номер карты, СБП и ФИО получателя."""
        details = config.MANUAL_PAYMENT_DETAILS
        self.assertIn("2202208867846645", details)
        self.assertIn("+79055356182", details)
        self.assertTrue("Захар Воробей" in details and "Захар В." in details)

    def test_env_file_contains_updated_details(self):
        """Файл .env содержит актуальные реквизиты."""
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("2202208867846645", content)
            self.assertIn("+79055356182", content)
            self.assertIn("Захар", content)

    async def test_manual_payment_message_rendering(self):
        """Сообщение ручной оплаты содержит 150 ₽ и актуальные реквизиты."""
        storage = MemoryStorage()
        key = StorageKey(bot_id=1, chat_id=123, user_id=456)
        state = FSMContext(storage=storage, key=key)

        callback = MagicMock()
        callback.data = "pay_manual_sub_1m"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await payments.cb_pay_manual(callback, state)

        callback.message.edit_text.assert_called_once()
        sent_text = callback.message.edit_text.call_args[0][0]
        self.assertIn("150 ₽", sent_text)
        self.assertIn("2202208867846645", sent_text)
        self.assertIn("+79055356182", sent_text)
        self.assertIn("Захар Воробей (Захар В.)", sent_text)


class TestTickerNormalization(unittest.TestCase):
    """Проверка R1: нормализация регистра и формата тикера."""

    def test_standard_tickers(self):
        self.assertEqual(scanner.normalize_symbol("btc"), "BTCUSDT")
        self.assertEqual(scanner.normalize_symbol("BTC"), "BTCUSDT")
        self.assertEqual(scanner.normalize_symbol("bTc"), "BTCUSDT")
        self.assertEqual(scanner.normalize_symbol("BTCUSDT"), "BTCUSDT")
        self.assertEqual(scanner.normalize_symbol("btcusdt"), "BTCUSDT")

    def test_delimiters_and_prefixes(self):
        self.assertEqual(scanner.normalize_symbol("btc/usdt"), "BTCUSDT")
        self.assertEqual(scanner.normalize_symbol("BTC-USDT"), "BTCUSDT")
        self.assertEqual(scanner.normalize_symbol("btc_usdt"), "BTCUSDT")
        self.assertEqual(scanner.normalize_symbol("$SOL"), "SOLUSDT")
        self.assertEqual(scanner.normalize_symbol("  eth  "), "ETHUSDT")

    def test_altcoins_and_meme_coins(self):
        self.assertEqual(scanner.normalize_symbol("1000pepe"), "1000PEPEUSDT")
        self.assertEqual(scanner.normalize_symbol("1000pepe/usdt"), "1000PEPEUSDT")
        self.assertEqual(scanner.normalize_symbol("DOGS"), "DOGSUSDT")
        self.assertEqual(scanner.normalize_symbol("ton"), "TONUSDT")

    def test_single_letter_tickers(self):
        """Проверка однобуквенных тикеров Binance (W, S, G, T)."""
        self.assertEqual(scanner.normalize_symbol("w"), "WUSDT")
        self.assertEqual(scanner.normalize_symbol("W"), "WUSDT")
        self.assertEqual(scanner.normalize_symbol("s"), "SUSDT")
        self.assertEqual(scanner.normalize_symbol("G"), "GUSDT")
        self.assertEqual(scanner.normalize_symbol("t"), "TUSDT")

    def test_cyrillic_homoglyphs(self):
        """Проверка авто-исправления случайного ввода в русской раскладке."""
        self.assertEqual(scanner.normalize_symbol("ВТС"), "BTCUSDT")  # В, Т, С кириллица
        self.assertEqual(scanner.normalize_symbol("етн"), "ETHUSDT")  # Е, Т, Н кириллица
        self.assertEqual(scanner.normalize_symbol("роl"), "POLUSDT")  # Р, О кириллица
        self.assertEqual(scanner.normalize_symbol("sоl"), "SOLUSDT")  # о кириллица

    def test_format_price(self):
        """Проверка форматирования цен разных порядков."""
        self.assertEqual(scanner.format_price(95000.5), "$95,000.50")
        self.assertEqual(scanner.format_price(1.5), "$1.50")
        self.assertEqual(scanner.format_price(0.05), "$0.0500")
        self.assertEqual(scanner.format_price(0.00000385), "$0.00000385")
        self.assertNotEqual(scanner.format_price(0.000000001), "$0.")
        self.assertEqual(scanner.format_price(0), "$0.00")

    def test_invalid_tickers(self):
        self.assertIsNone(scanner.normalize_symbol(""))
        self.assertIsNone(scanner.normalize_symbol("   "))
        self.assertIsNone(scanner.normalize_symbol("$$$"))
        self.assertIsNone(scanner.normalize_symbol("usdt"))
        self.assertIsNone(scanner.normalize_symbol("USDTUSDT"))
        self.assertIsNone(scanner.normalize_symbol("<script>alert(1)</script>"))
        self.assertIsNone(scanner.normalize_symbol("INVALID_TICKER_THAT_IS_WAY_TOO_LONG_FOR_BINANCE"))


class TestScannerAnalysis(unittest.IsolatedAsyncioTestCase):
    """Проверка R1: формирование экспресс-анализа и обработка ошибок."""

    async def test_valid_symbol_analysis(self):
        """Проверка анализа существующей монеты (mocked ticker)."""
        mock_ticker = {
            "symbol": "BTCUSDT",
            "lastPrice": "95000.50",
            "priceChangePercent": "2.45",
            "highPrice": "96000.00",
            "lowPrice": "94000.00",
            "quoteVolume": "1500000000.00"
        }
        with patch("services.scanner.get_ticker_24hr", new=AsyncMock(return_value=mock_ticker)), \
             patch("services.scanner.calculate_rsi", new=AsyncMock(side_effect=[45.0, 50.0])):
            report = await scanner.get_coin_analysis("BTCUSDT")
            self.assertIn("Экспресс-анализ: BTC / USDT", report)
            self.assertIn("$95,000.50", report)
            self.assertIn("+2.45%", report)
            self.assertIn("Индикатор RSI (1h): <b>45.0</b>", report)
            self.assertIn("Индикатор RSI (4h): <b>50.0</b>", report)
            self.assertIn("Вердикт сканера:", report)

    async def test_unknown_symbol_analysis(self):
        """Проверка анализа неизвестной монеты (возвращает ошибку без падения)."""
        with patch("services.scanner.get_ticker_24hr", new=AsyncMock(return_value=None)):
            report = await scanner.get_coin_analysis("UNKNOWN123USDT")
            self.assertIn("не найдена на бирже Binance", report)
            self.assertIn("UNKNOWN123", report)

    async def test_rsi_zero_extreme_oversold(self):
        """Проверка корректной обработки RSI = 0.0 (не превращается в '—' и 'Нейтрально')."""
        mock_ticker = {
            "symbol": "DUMPUSDT",
            "lastPrice": "1.00",
            "priceChangePercent": "-20.0",
            "highPrice": "1.50",
            "lowPrice": "0.90",
            "quoteVolume": "50000000.00"
        }
        with patch("services.scanner.get_ticker_24hr", new=AsyncMock(return_value=mock_ticker)), \
             patch("services.scanner.calculate_rsi", new=AsyncMock(side_effect=[0.0, 15.0])):
            report = await scanner.get_coin_analysis("DUMPUSDT")
            self.assertIn("Индикатор RSI (1h): <b>0.0</b> (Перепродан 🟢)", report)
            self.assertIn("СИЛЬНЫЙ СИГНАЛ НА ПОКУПКУ (Oversold)", report)
            self.assertNotIn("НЕЙТРАЛЬНЫЙ БОКОВИК", report)

    async def test_rsi_none_handles_cleanly(self):
        """Проверка монеты с недостаточной историей для RSI (не пишется ложное 'Нейтрально')."""
        mock_ticker = {
            "symbol": "NEWCOINUSDT",
            "lastPrice": "5.00",
            "priceChangePercent": "0.5",
            "highPrice": "5.10",
            "lowPrice": "4.90",
            "quoteVolume": "1000000.00"
        }
        with patch("services.scanner.get_ticker_24hr", new=AsyncMock(return_value=mock_ticker)), \
             patch("services.scanner.calculate_rsi", new=AsyncMock(side_effect=[None, None])):
            report = await scanner.get_coin_analysis("NEWCOINUSDT")
            self.assertIn("Индикатор RSI (1h): <b>—</b>\n", report)
            self.assertNotIn("— (Нейтрально ⚪)", report)

    async def test_flat_rsi_neutral_when_no_price_movement(self):
        """Проверка монеты с нулевым движением цены (RSI = 50.0 нейтрально, а не 100.0)."""
        fake_candles = [[0, 0, 0, 0, 10.0, 0, 0, 0, 0, 0, 0, 0]] * 30
        with patch("services.scanner.fetch_json", new=AsyncMock(return_value=fake_candles)):
            rsi = await scanner.calculate_rsi("FLATUSDT", "1h", 14)
            self.assertEqual(rsi, 50.0)

    async def test_sub_thousand_volume_formatting(self):
        """Проверка форматирования объема меньше $1,000 (не отображается $0.00M)."""
        mock_ticker = {
            "symbol": "LOWVOLUSDT",
            "lastPrice": "0.50",
            "priceChangePercent": "0.0",
            "highPrice": "0.50",
            "lowPrice": "0.50",
            "quoteVolume": "450.00"
        }
        with patch("services.scanner.get_ticker_24hr", new=AsyncMock(return_value=mock_ticker)), \
             patch("services.scanner.calculate_rsi", new=AsyncMock(return_value=50.0)):
            report = await scanner.get_coin_analysis("LOWVOLUSDT")
            self.assertIn("$450", report)
            self.assertNotIn("$0.00M", report)

    async def test_corrupted_volume_does_not_crash(self):
        """Проверка устойчивости к нечисловому quoteVolume (не падает с ValueError)."""
        mock_ticker = {
            "symbol": "CORRUPTUSDT",
            "lastPrice": "10.0",
            "priceChangePercent": "1.0",
            "highPrice": "11.0",
            "lowPrice": "9.0",
            "quoteVolume": "INVALID_VOLUME"
        }
        with patch("services.scanner.get_ticker_24hr", new=AsyncMock(return_value=mock_ticker)), \
             patch("services.scanner.calculate_rsi", new=AsyncMock(return_value=50.0)):
            report = await scanner.get_coin_analysis("CORRUPTUSDT")
            self.assertIn("Экспресс-анализ: CORRUPT / USDT", report)
            self.assertIn("$0", report)


class TestVipAccessControlAndHandlers(unittest.IsolatedAsyncioTestCase):
    """Проверка прав доступа VIP и FSM диалога ввода монеты."""

    async def asyncSetUp(self):
        self.storage = MemoryStorage()
        self.bot = MagicMock()

    def get_fsm_context(self, user_id: int, chat_id: int = 123) -> FSMContext:
        key = StorageKey(bot_id=1, chat_id=chat_id, user_id=user_id)
        return FSMContext(storage=self.storage, key=key)

    async def test_non_vip_coin_select_shows_teaser(self):
        """Пользователь без VIP при нажатии 'Анализ монеты' видит тизер."""
        callback = MagicMock()
        callback.from_user.id = 999001
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()
        state = self.get_fsm_context(999001)

        with patch("database.is_sub_active", new=AsyncMock(return_value=False)):
            await vip_services.cb_coin_select(callback, state)

        callback.message.edit_text.assert_called_once()
        sent_text = callback.message.edit_text.call_args[0][0]
        self.assertIn("доступен только для VIP-участников", sent_text)
        self.assertIn("150 ⭐", sent_text)

    async def test_vip_coin_select_shows_keyboard_with_custom_coin(self):
        """VIP пользователь видит клавиатуру с кнопкой 'Ввести свою монету'."""
        callback = MagicMock()
        callback.from_user.id = 999002
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()
        state = self.get_fsm_context(999002)

        with patch("database.is_sub_active", new=AsyncMock(return_value=True)):
            await vip_services.cb_coin_select(callback, state)

        callback.message.edit_text.assert_called_once()
        kb_arg = callback.message.edit_text.call_args[1]["reply_markup"]
        all_buttons = [btn.text for row in kb_arg.inline_keyboard for btn in row]
        self.assertTrue(any("Ввести свою монету" in b for b in all_buttons))

    async def test_non_vip_custom_coin_callback_blocked(self):
        """Пользователь без VIP не может запустить ввод своей монеты."""
        callback = MagicMock()
        callback.from_user.id = 999003
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()
        state = self.get_fsm_context(999003)

        with patch("database.is_sub_active", new=AsyncMock(return_value=False)):
            await vip_services.cb_custom_coin(callback, state)

        sent_text = callback.message.edit_text.call_args[0][0]
        self.assertIn("доступен только для VIP-участников", sent_text)
        # Состояние не должно установиться в waiting_for_ticker
        current_state = await state.get_state()
        self.assertIsNone(current_state)

    async def test_vip_custom_coin_sets_waiting_state(self):
        """VIP пользователь при нажатии 'Ввести свою монету' переходит в состояние ожидания тикера."""
        callback = MagicMock()
        callback.from_user.id = 999004
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()
        state = self.get_fsm_context(999004)

        with patch("database.is_sub_active", new=AsyncMock(return_value=True)):
            await vip_services.cb_custom_coin(callback, state)

        current_state = await state.get_state()
        self.assertEqual(current_state, vip_services.CustomCoinState.waiting_for_ticker.state)
        sent_text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Анализ собственной монеты", sent_text)

    async def test_vip_enters_valid_custom_ticker(self):
        """VIP вводит валидный тикер и получает отчет анализа."""
        message = MagicMock()
        message.from_user.id = 999005
        message.text = "SOL"
        loading_msg = MagicMock()
        loading_msg.edit_text = AsyncMock()
        message.answer = AsyncMock(return_value=loading_msg)
        state = self.get_fsm_context(999005)
        await state.set_state(vip_services.CustomCoinState.waiting_for_ticker)

        with patch("database.is_sub_active", new=AsyncMock(return_value=True)), \
             patch("services.scanner.get_coin_analysis", new=AsyncMock(return_value="REPORT_FOR_SOLUSDT")) as mock_analysis:
            await vip_services.process_custom_coin_ticker(message, state)

        mock_analysis.assert_called_once_with("SOLUSDT")
        loading_msg.edit_text.assert_called_once()
        self.assertEqual(loading_msg.edit_text.call_args[0][0], "REPORT_FOR_SOLUSDT")
        self.assertIsNone(await state.get_state())

    async def test_vip_enters_invalid_custom_ticker_format(self):
        """VIP вводит мусор вместо тикера — получает ошибку формата, бот не падает."""
        message = MagicMock()
        message.from_user.id = 999006
        message.text = "!!@@##$$"
        message.answer = AsyncMock()
        state = self.get_fsm_context(999006)
        await state.set_state(vip_services.CustomCoinState.waiting_for_ticker)

        with patch("database.is_sub_active", new=AsyncMock(return_value=True)):
            await vip_services.process_custom_coin_ticker(message, state)

        message.answer.assert_called_once()
        err_text = message.answer.call_args[0][0]
        self.assertIn("Некорректный формат тикера", err_text)

    async def test_vip_cancels_ticker_input(self):
        """VIP может отменить ввод тикера командой /cancel."""
        message = MagicMock()
        message.from_user.id = 999007
        message.text = "/cancel"
        message.answer = AsyncMock()
        state = self.get_fsm_context(999007)
        await state.set_state(vip_services.CustomCoinState.waiting_for_ticker)

        await vip_services.cmd_cancel_custom_coin(message, state)

        self.assertIsNone(await state.get_state())
        message.answer.assert_called_once()
        self.assertIn("отменен", message.answer.call_args[0][0])

    async def test_command_analyze_vip_and_non_vip(self):
        """Проверка команды /analyze для VIP и не-VIP."""
        # Не-VIP
        non_vip_msg = MagicMock()
        non_vip_msg.from_user.id = 999008
        non_vip_msg.text = "/analyze BTC"
        non_vip_msg.answer = AsyncMock()
        state1 = self.get_fsm_context(999008)

        with patch("database.is_sub_active", new=AsyncMock(return_value=False)):
            await vip_services.cmd_analyze_coin(non_vip_msg, state1)

        sent_text = non_vip_msg.answer.call_args[0][0]
        self.assertIn("доступен только для VIP-участников", sent_text)

        # VIP с аргументом
        vip_msg = MagicMock()
        vip_msg.from_user.id = 999009
        vip_msg.text = "/analyze ETH"
        loading_msg = MagicMock()
        loading_msg.edit_text = AsyncMock()
        vip_msg.answer = AsyncMock(return_value=loading_msg)
        state2 = self.get_fsm_context(999009)

        with patch("database.is_sub_active", new=AsyncMock(return_value=True)), \
             patch("services.scanner.get_coin_analysis", new=AsyncMock(return_value="REPORT_FOR_ETHUSDT")):
            await vip_services.cmd_analyze_coin(vip_msg, state2)

        loading_msg.edit_text.assert_called_once()
        self.assertEqual(loading_msg.edit_text.call_args[0][0], "REPORT_FOR_ETHUSDT")

    async def test_non_vip_cb_analyze_shows_teaser(self):
        """Не-VIP пользователь при нажатии analyze_BTCUSDT видит предложение оформить VIP."""
        callback = MagicMock()
        callback.from_user.id = 999010
        callback.data = "analyze_BTCUSDT"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        with patch("database.is_sub_active", new=AsyncMock(return_value=False)):
            await vip_services.cb_analyze_coin(callback)

        callback.message.edit_text.assert_called_once()
        sent_text = callback.message.edit_text.call_args[0][0]
        self.assertIn("доступен только для VIP-участников", sent_text)
        self.assertIn("150 ⭐", sent_text)

    async def test_vip_custom_coin_exception_clears_state(self):
        """При исключении в анализе монеты FSM состояние пользователя корректно сбрасывается."""
        message = MagicMock()
        message.from_user.id = 999011
        message.text = "BTC"
        loading_msg = MagicMock()
        loading_msg.edit_text = AsyncMock()
        message.answer = AsyncMock(return_value=loading_msg)
        state = self.get_fsm_context(999011)
        await state.set_state(vip_services.CustomCoinState.waiting_for_ticker)

        with patch("database.is_sub_active", new=AsyncMock(return_value=True)), \
             patch("services.scanner.get_coin_analysis", new=AsyncMock(side_effect=RuntimeError("Binance network error"))):
            await vip_services.process_custom_coin_ticker(message, state)

        # FSM состояние гарантированно очищено
        self.assertIsNone(await state.get_state())
        loading_msg.edit_text.assert_called_once()
        self.assertIn("Ошибка при получении данных", loading_msg.edit_text.call_args[0][0])

    async def test_manual_payment_cancel(self):
        """Пользователь может отменить ожидание чека командой /cancel."""
        message = MagicMock()
        message.from_user.id = 999012
        message.answer = AsyncMock()
        state = self.get_fsm_context(999012)
        await state.set_state(payments.ManualPaymentState.waiting_for_receipt)

        await payments.cmd_cancel_manual_payment(message, state)

        self.assertIsNone(await state.get_state())
        message.answer.assert_called_once()
        self.assertIn("Оплата отменена", message.answer.call_args[0][0])

    async def test_start_command_clears_waiting_ticker_state(self):
        """Команда /start сбрасывает FSM состояние CustomCoinState.waiting_for_ticker."""
        message = MagicMock()
        message.from_user.id = 999013
        message.from_user.username = "testuser"
        message.from_user.first_name = "Alex"
        message.text = "/start"
        message.answer = AsyncMock()
        state = self.get_fsm_context(999013)
        await state.set_state(vip_services.CustomCoinState.waiting_for_ticker)

        with patch("database.get_or_create_user", new=AsyncMock()):
            await user.cmd_start(message, state)

        self.assertIsNone(await state.get_state())
        message.answer.assert_called_once()
        self.assertIn("Приветствуем", message.answer.call_args[0][0])

    async def test_start_command_clears_manual_payment_state(self):
        """Команда /start сбрасывает FSM состояние ManualPaymentState.waiting_for_receipt."""
        message = MagicMock()
        message.from_user.id = 999014
        message.from_user.username = "testuser2"
        message.from_user.first_name = "Alex2"
        message.text = "/start"
        message.answer = AsyncMock()
        state = self.get_fsm_context(999014)
        await state.set_state(payments.ManualPaymentState.waiting_for_receipt)

        with patch("database.get_or_create_user", new=AsyncMock()):
            await user.cmd_start(message, state)

        self.assertIsNone(await state.get_state())
        message.answer.assert_called_once()

    async def test_text_message_in_manual_payment_shows_prompt(self):
        """Отправка текста при ожидании чека выводит подсказку о необходимости прикрепить фото/файл."""
        message = MagicMock()
        message.from_user.id = 999015
        message.text = "Я оплатил 150 рублей"
        message.answer = AsyncMock()

        await payments.process_invalid_receipt_text(message)

        message.answer.assert_called_once()
        sent = message.answer.call_args[0][0]
        self.assertIn("Пожалуйста, отправьте чек об оплате", sent)
        self.assertIn("/cancel", sent)

    async def test_invalid_ticker_content_prompt(self):
        """Отправка нетекстового контента при вводе тикера монеты выводит подсказку."""
        message = MagicMock()
        message.from_user.id = 999016
        message.answer = AsyncMock()

        await vip_services.process_invalid_ticker_content(message)

        message.answer.assert_called_once()
        self.assertIn("текстовое сообщение с тикером монеты", message.answer.call_args[0][0])

    async def test_dispatcher_start_in_custom_coin_state(self):
        """Интеграционный тест: Dispatcher доставляет /start в cmd_start и сбрасывает CustomCoinState."""
        routers = [payments.router, vip_services.router, user.router]
        old_parents = {r: getattr(r, "_parent_router", None) for r in routers}
        for r in routers:
            r._parent_router = None

        dp = Dispatcher(storage=MemoryStorage())
        for r in routers:
            dp.include_router(r)

        bot = Bot(token="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")
        sent_messages = []

        async def mock_make_request(bot_inst, method, timeout=None):
            sent_messages.append(method)
            return {"message_id": 100, "date": 100, "chat": {"id": 999017, "type": "private"}}

        try:
            with patch.object(bot.session, "make_request", side_effect=mock_make_request):
                key = StorageKey(bot_id=bot.id, chat_id=999017, user_id=999017)
                state = FSMContext(storage=dp.storage, key=key)
                await state.set_state(vip_services.CustomCoinState.waiting_for_ticker)

                u = User(id=999017, is_bot=False, first_name="DispatcherTester")
                c = Chat(id=999017, type="private")
                m = Message(message_id=1, date=100, chat=c, from_user=u, text="/start")

                with patch("database.get_or_create_user", new=AsyncMock()):
                    await dp.feed_update(bot=bot, update=Update(update_id=1, message=m))

                # FSM состояние гарантированно очищено
                self.assertIsNone(await state.get_state())
                # Ответ отправлен из cmd_start, а не из process_invalid_ticker_content
                self.assertTrue(len(sent_messages) > 0)
                self.assertIn("Приветствуем", sent_messages[-1].text)
        finally:
            await bot.session.close()
            for r, p in old_parents.items():
                r._parent_router = p

    async def test_cmd_analyze_with_caption_only(self):
        """Проверка команды /analyze при отправке с фото/документом (message.text is None)."""
        vip_msg = MagicMock()
        vip_msg.from_user.id = 999018
        vip_msg.text = None
        vip_msg.caption = "/analyze BTC"
        loading_msg = MagicMock()
        loading_msg.edit_text = AsyncMock()
        vip_msg.answer = AsyncMock(return_value=loading_msg)
        state = self.get_fsm_context(999018)

        with patch("database.is_sub_active", new=AsyncMock(return_value=True)), \
             patch("services.scanner.get_coin_analysis", new=AsyncMock(return_value="REPORT_FOR_BTC")):
            await vip_services.cmd_analyze_coin(vip_msg, state)

        loading_msg.edit_text.assert_called_once()
        self.assertEqual(loading_msg.edit_text.call_args[0][0], "REPORT_FOR_BTC")

    async def test_cmd_start_with_caption_only(self):
        """Проверка /start когда message.text is None (например, пересланное медиа с подписью)."""
        message = MagicMock()
        message.from_user.id = 999019
        message.from_user.username = "captionuser"
        message.from_user.first_name = "CaptionTester"
        message.text = None
        message.caption = "/start ref_12345"
        message.answer = AsyncMock()
        state = self.get_fsm_context(999019)

        with patch("database.get_or_create_user", new=AsyncMock()) as mock_create:
            await user.cmd_start(message, state)

        mock_create.assert_called_once_with(999019, "captionuser", "CaptionTester", 12345)
        message.answer.assert_called_once()
        self.assertIn("Приветствуем", message.answer.call_args[0][0])

    async def test_non_receipt_media_in_manual_payment_shows_prompt(self):
        """Отправка не-чека (стикер, голосовое) при ожидании чека выводит подсказку."""
        message = MagicMock()
        message.from_user.id = 999020
        message.text = None
        message.photo = None
        message.document = None
        message.answer = AsyncMock()

        await payments.process_invalid_receipt_text(message)

        message.answer.assert_called_once()
        sent = message.answer.call_args[0][0]
        self.assertIn("Пожалуйста, отправьте чек об оплате", sent)


if __name__ == "__main__":
    unittest.main()
