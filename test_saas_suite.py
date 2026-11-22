"""
================================================================================
           CryptoRadar SaaS Platform — Unified End-to-End Test Suite
================================================================================
Comprehensive verification testing:
1. SQLite Database Tables, Schema & Foreign Key / Relational Integrity.
2. Web Server & REST API Endpoints (Sunny & Rainy day scenarios).
3. Technical Analysis & AI Forecast Engine with Microsecond In-Memory Caching.
4. Affiliate Rev-Share Engine (30% on Telegram Stars & RUB Fiat Payments).
5. Traffic Funnel Generators (Marketing Posts & 30-sec Viral Video Scripts).
6. Telegram Bot Routers, Filters & UI Keyboards (WebAppInfo & Inline Buttons).
7. End-to-End Lifecycle Simulation (Partner Signup -> Traffic -> Sub -> Rev-share).
================================================================================
"""

import asyncio
import os
import sys
import time
import json
import unittest
from unittest.mock import AsyncMock, patch


import aiosqlite
from aiohttp.test_utils import TestClient, TestServer
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import WebAppInfo

import config
import database as db
import generate_reel
from handlers import admin, payments, user, vip_services
import keyboards as kb
from services import affiliate, ai_analytics, scanner, traffic_funnel
import services.notion_sync as notion_sync

import web_server

TEST_DB_PATH = "test_saas_suite_database.db"


class BaseSaaSTestCase(unittest.IsolatedAsyncioTestCase):
    """Базовый класс тестов с изолированной временной базой данных."""

    async def asyncSetUp(self):
        self.original_db = db.DB_PATH
        db.DB_PATH = TEST_DB_PATH
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass
        await db.init_db()

    async def asyncTearDown(self):
        db.DB_PATH = self.original_db
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass


# ==============================================================================
# SUITE 1: SQLite Database Tables, Schema & Relational Integrity
# ==============================================================================
class TestDatabaseAndRelations(BaseSaaSTestCase):
    """Проверка создания всех таблиц, структуры полей и реляционных связей."""

    async def test_all_seven_tables_exist(self):
        """Проверка наличия всех 7 таблиц архитектуры SaaS в SQLite."""
        async with aiosqlite.connect(TEST_DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            tables = {row[0] for row in await cursor.fetchall()}

        expected_tables = {
            "users",
            "payments",
            "posted_news",
            "posted_alerts",
            "partners",
            "affiliate_earnings",
            "payout_requests"
        }
        self.assertTrue(
            expected_tables.issubset(tables),
            f"Не все таблицы созданы. Ожидалось: {expected_tables}, обнаружено: {tables}"
        )

    async def test_table_schemas_and_columns(self):
        """Проверка колонок и типов данных в ключевых таблицах."""
        async with aiosqlite.connect(TEST_DB_PATH) as conn:
            # Таблица users
            cursor = await conn.execute("PRAGMA table_info(users);")
            user_cols = {row[1] for row in await cursor.fetchall()}
            self.assertTrue({"user_id", "username", "first_name", "referrer_id", "sub_until", "created_at"}.issubset(user_cols))

            # Таблица payments
            cursor = await conn.execute("PRAGMA table_info(payments);")
            pay_cols = {row[1] for row in await cursor.fetchall()}
            self.assertTrue({"id", "user_id", "tariff_key", "amount", "currency", "status", "created_at"}.issubset(pay_cols))

            # Таблица partners
            cursor = await conn.execute("PRAGMA table_info(partners);")
            partner_cols = {row[1] for row in await cursor.fetchall()}
            self.assertTrue({
                "user_id", "partner_code", "channel_name", "channel_link", "commission_rate",
                "balance_stars", "balance_rub", "total_earned_stars", "total_earned_rub",
                "payout_details", "is_active", "created_at"
            }.issubset(partner_cols))

            # Таблица affiliate_earnings
            cursor = await conn.execute("PRAGMA table_info(affiliate_earnings);")
            earn_cols = {row[1] for row in await cursor.fetchall()}
            self.assertTrue({
                "id", "partner_id", "referral_user_id", "payment_id", "tariff_key",
                "amount_paid", "commission_amount", "currency", "created_at"
            }.issubset(earn_cols))

            # Таблица payout_requests
            cursor = await conn.execute("PRAGMA table_info(payout_requests);")
            payout_cols = {row[1] for row in await cursor.fetchall()}
            self.assertTrue({"id", "partner_id", "amount", "currency", "details", "status", "created_at", "processed_at"}.issubset(payout_cols))

    async def test_relational_integrity_joins(self):
        """Проверка целостности связей между пользователями, партнерами, платежами и ревшарой."""
        partner_id = 901
        buyer_id = 902

        # 1. Регистрация партнера и покупателя с реферером
        await db.register_or_get_partner(partner_id, partner_code="alpha_ref", commission_rate=0.30)
        await db.get_or_create_user(partner_id, "partner_user", "Partner")
        await db.get_or_create_user(buyer_id, "buyer_user", "Buyer", referrer_id=partner_id)

        # 2. Фиксация платежа
        pay_id = await db.record_payment(buyer_id, "sub_1m", 150, "XTR", "approved")

        # 3. Начисление комиссии
        earning_id = await db.record_affiliate_earning(
            partner_id=partner_id,
            referral_user_id=buyer_id,
            payment_id=pay_id,
            tariff_key="sub_1m",
            amount_paid=150,
            commission_amount=45,
            currency="XTR"
        )

        # 4. Запрос на выплату
        _, _, payout_id = await db.create_payout_request(partner_id, 40, "XTR", "@partner_wallet")

        # 5. Проверка реляционного SQL-соединения всех сущностей
        async with aiosqlite.connect(TEST_DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT 
                    e.id AS earning_id,
                    p.partner_code,
                    u_buyer.username AS buyer_username,
                    u_partner.username AS partner_username,
                    pay.amount AS paid_amount,
                    e.commission_amount,
                    pr.amount AS requested_payout
                FROM affiliate_earnings e
                JOIN partners p ON e.partner_id = p.user_id
                JOIN users u_partner ON u_partner.user_id = p.user_id
                JOIN users u_buyer ON u_buyer.user_id = e.referral_user_id
                JOIN payments pay ON pay.id = e.payment_id
                LEFT JOIN payout_requests pr ON pr.partner_id = p.user_id
                WHERE e.id = ?
            """, (earning_id,))
            rel_row = await cursor.fetchone()

        self.assertIsNotNone(rel_row)
        self.assertEqual(rel_row["partner_code"], "alpha_ref")
        self.assertEqual(rel_row["buyer_username"], "buyer_user")
        self.assertEqual(rel_row["partner_username"], "partner_user")
        self.assertEqual(rel_row["paid_amount"], 150)
        self.assertEqual(rel_row["commission_amount"], 45)
        self.assertEqual(rel_row["requested_payout"], 40)

    async def test_rainy_day_database_handling(self):
        """Rainy Day: проверка защиты от саморефералов, дубликатов новостей и кулдаунов алертов."""
        # Самореферал предотвращается: referrer_id должен стать None
        user_self = await db.get_or_create_user(555, "self_user", "Self", referrer_id=555)
        self.assertIsNone(user_self["referrer_id"])

        # Запрос несуществующего пользователя возвращает None
        self.assertIsNone(await db.get_user(999999999))
        self.assertFalse(await db.is_sub_active(999999999))

        # Защита от повторной публикации новостей
        news_url = "https://crypto.com/news/123"
        self.assertFalse(await db.is_news_posted(news_url))
        await db.mark_news_as_posted(news_url, "Bitcoin ATH")
        self.assertTrue(await db.is_news_posted(news_url))

        # Защита от частых алертов по монете
        self.assertTrue(await db.can_post_alert("BTCUSDT", "rsi_oversold", cooldown_hours=2))
        await db.record_alert("BTCUSDT", "rsi_oversold")
        self.assertFalse(await db.can_post_alert("BTCUSDT", "rsi_oversold", cooldown_hours=2))


# ==============================================================================
# SUITE 2: Web Server & REST API Endpoints (Sunny & Rainy Day)
# ==============================================================================
class TestWebServerAndAPIEndpoints(BaseSaaSTestCase):
    """Проверка всех веб-эндпоинтов, SPA-статики, CORS и API кодов ответа."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.app = web_server.create_app()
        self.server = TestServer(self.app)
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await super().asyncTearDown()

    async def test_static_assets_serving(self):
        """Sunny Day: проверка раздачи index.html, style.css и app.js."""
        # GET /
        resp_index = await self.client.get("/")
        self.assertEqual(resp_index.status, 200)
        html_text = await resp_index.text()
        self.assertIn("<!DOCTYPE html>", html_text)
        self.assertIn("CryptoRadar PRO", html_text)
        self.assertIn("telegram-web-app.js", html_text)
        self.assertIn("tv_chart_container", html_text)
        self.assertIn("profile-modal", html_text)
        self.assertIn("profile-vip-days", html_text)
        self.assertIn("profile-reg-date", html_text)

        # GET /style.css
        resp_css = await self.client.get("/style.css")
        self.assertEqual(resp_css.status, 200)
        css_text = await resp_css.text()
        self.assertIn("glass-card", css_text)
        self.assertIn("--accent-cyan", css_text)

        # GET /app.js
        resp_js = await self.client.get("/app.js")
        self.assertEqual(resp_js.status, 200)
        js_text = await resp_js.text()
        self.assertIn("Telegram", js_text)
        self.assertIn("TradingView", js_text)

    async def test_health_endpoints(self):
        """Sunny Day: проверка /health и /api/health."""
        for path in ("/health", "/api/health"):
            resp = await self.client.get(path)
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data.get("status"), "ok")
            self.assertIn("CryptoRadar", data.get("service", ""))
            self.assertEqual(data.get("version"), "2.0.0")

    async def test_market_overview_endpoint(self):
        """Sunny Day: проверка /api/market-overview с котировками и глобальными метриками."""
        resp = await self.client.get("/api/market-overview")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("global", data)
        self.assertIn("tickers", data)
        self.assertGreaterEqual(len(data["tickers"]), 4)

        first_ticker = data["tickers"][0]
        self.assertIn("symbol", first_ticker)
        self.assertIn("price", first_ticker)
        self.assertIn("price_formatted", first_ticker)
        self.assertIn("rsi_1h", first_ticker)
        self.assertIn("status", first_ticker)

    async def test_signals_endpoint(self):
        """Sunny Day: проверка /api/signals со свободными и VIP-сигналами."""
        resp = await self.client.get("/api/signals")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")
        signals = data.get("signals", [])
        self.assertGreaterEqual(len(signals), 3)

        free_sigs = [s for s in signals if not s.get("is_vip")]
        vip_sigs = [s for s in signals if s.get("is_vip")]
        self.assertGreater(len(free_sigs), 0, "Должны быть бесплатные лид-магнит сигналы")
        self.assertGreater(len(vip_sigs), 0, "Должны быть закрытые VIP-сигналы")

        for sig in signals:
            self.assertIn("symbol", sig)
            self.assertIn("confidence", sig)
            self.assertIn("entry_range", sig)
            self.assertIn("tp1", sig)
            self.assertIn("stop_loss", sig)

    async def test_tariffs_endpoint(self):
        """Sunny Day: проверка /api/tariffs с ценами 150 Stars и 150 RUB."""
        resp = await self.client.get("/api/tariffs")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "success")
        tariffs = data.get("tariffs", [])
        self.assertEqual(len(tariffs), 3)

        sub_1m = next((t for t in tariffs if t["key"] == "sub_1m"), None)
        self.assertIsNotNone(sub_1m)
        self.assertEqual(sub_1m["stars"], 150)
        self.assertEqual(sub_1m["rub_price"], 150)

        pay_info = data.get("payment_info", {})
        self.assertTrue(pay_info.get("stars_enabled"))
        self.assertTrue(pay_info.get("rub_enabled"))

    async def test_user_status_sunny_and_rainy(self):
        """Sunny & Rainy: проверка /api/user-status для гостей, зарегистрированных, VIP и админа."""
        # 1. Rainy: Запрос без user_id -> Гость
        resp_guest = await self.client.get("/api/user-status")
        self.assertEqual(resp_guest.status, 200)
        guest_data = await resp_guest.json()
        self.assertTrue(guest_data["user"]["is_guest"])
        self.assertFalse(guest_data["user"]["is_vip"])
        self.assertEqual(guest_data["vip_days_left"], 0)
        self.assertEqual(guest_data["registration_date"], "—")

        # 2. Rainy: Некорректный строковый user_id -> Гость
        resp_bad_id = await self.client.get("/api/user-status?user_id=not_a_number")
        bad_id_data = await resp_bad_id.json()
        self.assertTrue(bad_id_data["user"]["is_guest"])
        self.assertEqual(bad_id_data["vip_days_left"], 0)

        # 3. Sunny: Зарегистрированный обычный пользователь
        await db.get_or_create_user(777111, "trader_joe", "Joe")
        resp_user = await self.client.get("/api/user-status?user_id=777111")
        user_data = await resp_user.json()
        self.assertFalse(user_data["user"]["is_guest"])
        self.assertEqual(user_data["user"]["user_id"], 777111)
        self.assertFalse(user_data["user"]["is_vip"])
        self.assertIsNone(user_data["user"]["vip_link"])
        self.assertEqual(user_data["user"]["vip_days_left"], 0)
        self.assertEqual(user_data["user"]["vip_days_text"], "0 дн. (Нет подписки)")
        self.assertIn("UTC", user_data["user"]["registration_date"])

        # 4. Sunny: VIP пользователь с активной подпиской
        await db.add_subscription_days(777111, 30)
        resp_vip = await self.client.get("/api/user-status?user_id=777111")
        vip_data = await resp_vip.json()
        self.assertTrue(vip_data["user"]["is_vip"])
        self.assertIsNotNone(vip_data["user"]["sub_until"])
        self.assertIsNotNone(vip_data["user"]["vip_link"])
        self.assertGreaterEqual(vip_data["user"]["vip_days_left"], 29)
        self.assertIn("дн.", vip_data["user"]["vip_days_text"])

        # 5. Sunny: Администратор (config.ADMIN_ID = 1639805642)
        admin_id = config.ADMIN_ID or 1639805642
        resp_admin = await self.client.get(f"/api/user-status?user_id={admin_id}")
        self.assertEqual(resp_admin.status, 200)
        admin_data = await resp_admin.json()
        self.assertTrue(admin_data["user"]["is_vip"])
        self.assertEqual(admin_data["user"]["vip_days_text"], "Бессрочно (Admin)")
        self.assertGreater(admin_data["user"]["vip_days_left"], 1000)
        self.assertIsNotNone(admin_data["user"]["registration_date"])
        self.assertIsNotNone(admin_data["registration_date"])

    async def test_ai_forecast_endpoint_sunny_and_rainy(self):
        """Sunny & Rainy: проверка /api/ai-forecast через GET и POST, валидация ошибок."""
        # 1. Sunny: GET с валидным символом BTC
        resp_btc = await self.client.get("/api/ai-forecast?symbol=BTC")
        self.assertEqual(resp_btc.status, 200)
        data_btc = await resp_btc.json()
        self.assertEqual(data_btc.get("status"), "success")
        self.assertEqual(data_btc.get("symbol"), "BTCUSDT")
        self.assertIn("bias", data_btc)
        self.assertIn("probability", data_btc)
        self.assertIn("tp1", data_btc)
        self.assertIn("stop_loss", data_btc)
        self.assertIn("indicators", data_btc)

        # 2. Sunny: POST с телом JSON {"symbol": "ETH"}
        resp_post = await self.client.post("/api/ai-forecast", json={"symbol": "ETH"})
        self.assertEqual(resp_post.status, 200)
        data_post = await resp_post.json()
        self.assertEqual(data_post.get("status"), "success")
        self.assertEqual(data_post.get("symbol"), "ETHUSDT")

        # 3. Rainy: Запрос без указания символа -> 400 Bad Request
        resp_empty = await self.client.get("/api/ai-forecast")
        self.assertEqual(resp_empty.status, 400)
        data_empty = await resp_empty.json()
        self.assertEqual(data_empty.get("status"), "error")
        self.assertIn("обязателен", data_empty.get("message", ""))

        # 4. Rainy: Некорректный тикер со спецсимволами -> 400 Bad Request
        resp_invalid = await self.client.get("/api/ai-forecast?symbol=@@@BAD_COIN$$$")
        self.assertEqual(resp_invalid.status, 400)
        data_invalid = await resp_invalid.json()
        self.assertEqual(data_invalid.get("status"), "error")

        # 5. Rainy: 404 для неизвестного маршрута
        resp_404 = await self.client.get("/api/non-existent-endpoint")
        self.assertEqual(resp_404.status, 404)

    async def test_cors_middleware_headers(self):
        """Проверка поддержки CORS заголовков для бесшовной работы TMA."""
        resp = await self.client.options("/api/market-overview")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("GET", resp.headers.get("Access-Control-Allow-Methods", ""))

    async def test_notion_api_endpoints(self):
        """Проверка REST API эндпоинтов телеметрии Notion Command Center."""
        resp_metrics = await self.client.get("/api/notion/metrics")
        self.assertEqual(resp_metrics.status, 200)
        data = await resp_metrics.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("metrics", data)
        self.assertIn("command_center_url", data)

        resp_sync = await self.client.post("/api/notion/sync")
        self.assertEqual(resp_sync.status, 200)
        sync_data = await resp_sync.json()
        self.assertTrue(sync_data["success"])
        self.assertIn("markdown_block", sync_data)

    async def test_signal_card_endpoint_sunny_and_rainy(self):
        """Sunny & Rainy: проверка /api/signal-card (Task 12) - PNG рендеринг, кеш и JSON."""
        # 1. Rainy: missing symbol
        resp_missing = await self.client.get("/api/signal-card")
        self.assertEqual(resp_missing.status, 400)
        err_json = await resp_missing.json()
        self.assertEqual(err_json["status"], "error")

        # 2. Rainy: invalid symbol
        resp_invalid = await self.client.get("/api/signal-card?symbol=@@INVALID@@")
        self.assertEqual(resp_invalid.status, 400)
        err_invalid = await resp_invalid.json()
        self.assertEqual(err_invalid["status"], "error")

        # 3. Sunny: direct PNG image response
        resp_png = await self.client.get("/api/signal-card?symbol=BTC")
        self.assertEqual(resp_png.status, 200)
        self.assertIn("image/png", resp_png.headers.get("Content-Type", ""))
        self.assertIn("max-age=60", resp_png.headers.get("Cache-Control", ""))
        png_bytes = await resp_png.read()
        self.assertGreater(len(png_bytes), 10000)

        # 4. Sunny: JSON format with base64 image
        resp_json = await self.client.get("/api/signal-card?symbol=BTC&format=json")
        self.assertEqual(resp_json.status, 200)
        card_data = await resp_json.json()
        self.assertEqual(card_data["status"], "success")
        self.assertEqual(card_data["symbol"], "BTCUSDT")
        self.assertIn("image_base64", card_data)
        self.assertTrue(card_data["image_base64"].startswith("data:image/png;base64,"))
        self.assertIn("price", card_data)
        self.assertIn("probability", card_data)



# ==============================================================================
# SUITE 3: Technical Analysis & AI Forecast Engine with Caching
# ==============================================================================
class TestTechnicalAnalysisAndAIEngine(unittest.IsolatedAsyncioTestCase):
    """Проверка математики индикаторов (RSI, EMA, Bollinger, ATR), скоринга и кеша."""

    def test_indicator_math_calculations(self):
        """Проверка расчетов RSI, EMA, Bollinger Bands, Volume Spike и ATR."""
        # 1. RSI
        flat_prices = [100.0] * 30
        self.assertEqual(ai_analytics.calculate_rsi_series(flat_prices, 14), 50.0)

        up_prices = [float(i) for i in range(1, 30)]
        self.assertGreater(ai_analytics.calculate_rsi_series(up_prices, 14), 90.0)

        down_prices = [float(60 - i) for i in range(1, 30)]
        self.assertLess(ai_analytics.calculate_rsi_series(down_prices, 14), 10.0)

        # Недостаточно данных для RSI
        self.assertIsNone(ai_analytics.calculate_rsi_series([10.0, 11.0], 14))

        # 2. EMA
        trend_prices = [10.0 + (i * 0.5) for i in range(60)]
        ema_20 = ai_analytics.calculate_ema(trend_prices, 20)
        ema_50 = ai_analytics.calculate_ema(trend_prices, 50)
        self.assertIsNotNone(ema_20)
        self.assertIsNotNone(ema_50)
        self.assertGreater(ema_20, ema_50, "В восходящем тренде EMA-20 должна быть выше EMA-50")
        self.assertIsNone(ai_analytics.calculate_ema([10.0], 20))

        # 3. Bollinger Bands
        bb_data = [100.0 + (3.0 if i % 2 == 0 else -3.0) for i in range(25)]
        bb = ai_analytics.calculate_bollinger_bands(bb_data, period=20, num_std=2.0)
        self.assertGreater(bb["upper"], bb["middle"])
        self.assertGreater(bb["middle"], bb["lower"])
        self.assertGreater(bb["bandwidth"], 0.0)

        # 4. Volume Spike
        normal_vols = [1000.0] * 20
        vol_norm = ai_analytics.calculate_volume_spike(normal_vols, period=20)
        self.assertFalse(vol_norm["is_spike"])
        self.assertEqual(vol_norm["spike_ratio"], 1.0)

        surge_vols = [1000.0] * 20 + [3200.0]  # 3.2x аномальный объем
        vol_surge = ai_analytics.calculate_volume_spike(surge_vols, period=20)
        self.assertTrue(vol_surge["is_spike"])
        self.assertGreaterEqual(vol_surge["spike_ratio"], 3.0)

        # 5. ATR
        highs = [105.0 + i for i in range(30)]
        lows = [95.0 + i for i in range(30)]
        closes = [100.0 + i for i in range(30)]
        atr = ai_analytics.calculate_atr(highs, lows, closes, 14)
        self.assertGreater(atr, 0.0)

    def test_quantitative_heuristic_fallback_scenarios(self):
        """Проверка синтеза торговых сетапов (Strong Long, Scalp Long, Short, Neutral)."""
        # Strong Long
        synth_long = ai_analytics.synthesize_quantitative_forecast(
            symbol="BTCUSDT", ticker_name="BTC", price=90000.0, change_24h=3.5,
            volume_24h=1e9, rsi_1h=58.0, rsi_4h=60.0,
            bb={"middle": 89000.0, "upper": 92000.0, "lower": 86000.0, "percent_b": 0.65, "bandwidth": 6.7},
            ema_20=89500.0, ema_50=88000.0, vol_spike={"spike_ratio": 2.0, "is_spike": True}, atr=1200.0
        )
        self.assertEqual(synth_long["bias"], ai_analytics.BIAS_STRONG_LONG)
        self.assertGreaterEqual(synth_long["probability"], 70)
        self.assertGreater(synth_long["tp1_price"], 90000.0)
        self.assertLess(synth_long["stop_loss_price"], 90000.0)

        # Scalp Long (Oversold)
        synth_oversold = ai_analytics.synthesize_quantitative_forecast(
            symbol="SOLUSDT", ticker_name="SOL", price=200.0, change_24h=-6.0,
            volume_24h=5e8, rsi_1h=27.5, rsi_4h=34.0,
            bb={"middle": 215.0, "upper": 230.0, "lower": 200.0, "percent_b": 0.02, "bandwidth": 14.0},
            ema_20=210.0, ema_50=220.0, vol_spike={"spike_ratio": 1.1, "is_spike": False}, atr=5.0
        )
        self.assertEqual(synth_oversold["bias"], ai_analytics.BIAS_SCALP_LONG)
        self.assertGreater(synth_oversold["tp1_price"], 200.0)
        self.assertLess(synth_oversold["stop_loss_price"], 200.0)

        # Short breakdown
        synth_short = ai_analytics.synthesize_quantitative_forecast(
            symbol="ETHUSDT", ticker_name="ETH", price=3000.0, change_24h=-5.5,
            volume_24h=8e8, rsi_1h=39.0, rsi_4h=41.0,
            bb={"middle": 3150.0, "upper": 3300.0, "lower": 3000.0, "percent_b": 0.03, "bandwidth": 9.5},
            ema_20=3120.0, ema_50=3200.0, vol_spike={"spike_ratio": 1.9, "is_spike": True}, atr=65.0
        )
        self.assertIn(synth_short["bias"], (ai_analytics.BIAS_STRONG_SHORT, ai_analytics.BIAS_SCALP_SHORT))
        self.assertLess(synth_short["tp1_price"], 3000.0)
        self.assertGreater(synth_short["stop_loss_price"], 3000.0)

        # Neutral / Chop
        synth_neutral = ai_analytics.synthesize_quantitative_forecast(
            symbol="TONUSDT", ticker_name="TON", price=5.50, change_24h=0.1,
            volume_24h=3e7, rsi_1h=50.0, rsi_4h=49.5,
            bb={"middle": 5.50, "upper": 5.65, "lower": 5.35, "percent_b": 0.50, "bandwidth": 5.4},
            ema_20=5.50, ema_50=5.50, vol_spike={"spike_ratio": 0.9, "is_spike": False}, atr=0.10
        )
        self.assertEqual(synth_neutral["bias"], ai_analytics.BIAS_NEUTRAL)

    async def test_ai_forecast_caching_and_formatting(self):
        """Проверка 3-минутного кеша в памяти и HTML-форматирования для Telegram."""
        ai_analytics.clear_ai_cache()

        # 1-й вызов: свежий расчет
        t0 = time.time()
        res1 = await scanner.get_ai_forecast("BTC")
        t1 = time.time()
        self.assertEqual(res1["status"], "success")
        self.assertFalse(res1["cached"])

        # 2-й вызов: из кеша с микросекундной задержкой
        t2 = time.time()
        res2 = await scanner.get_ai_forecast("BTC")
        t3 = time.time()
        self.assertEqual(res2["status"], "success")
        self.assertTrue(res2["cached"])
        self.assertLess(t3 - t2, 0.05, "Кешированный ответ должен возвращаться быстрее 50 мс")

        # Force refresh сбрасывает кеш
        res3 = await ai_analytics.get_ai_market_forecast("BTC", force_refresh=True)
        self.assertFalse(res3["cached"])

        # Проверка Telegram HTML форматирования
        tg_text = ai_analytics.format_ai_forecast_telegram(res1)
        self.assertIn("AI Market Intelligence", tg_text)
        self.assertIn("Торговый вердикт (Bias):", tg_text)
        self.assertIn("Цель 1 (TP 1):", tg_text)
        self.assertIn("Stop-Loss", tg_text)
        self.assertIn("RSI:", tg_text)
        self.assertIn("Bollinger:", tg_text)


# ==============================================================================
# SUITE 4: Affiliate Rev-Share Engine (30% on Stars & RUB Payments)
# ==============================================================================
class TestAffiliateRevShareEngine(BaseSaaSTestCase):
    """Проверка B2B партнерской программы, слагов, начисления 30% rev-share и выплат."""

    def test_commission_calculation(self):
        """Проверка математики 30% комиссии."""
        self.assertEqual(affiliate.calculate_commission(150, 0.30), 45)
        self.assertEqual(affiliate.calculate_commission(350, 0.30), 105)
        self.assertEqual(affiliate.calculate_commission(1200, 0.30), 360)
        self.assertEqual(affiliate.calculate_commission(3500, 0.30), 1050)
        self.assertEqual(affiliate.calculate_commission(0, 0.30), 0)

    async def test_partner_slug_rules(self):
        """Sunny & Rainy: валидация реферальных слагов."""
        await db.register_or_get_partner(301, partner_code="partner_301")
        await db.register_or_get_partner(302, partner_code="crypto_insider")

        # Rainy: слишком короткий (< 3)
        ok, msg = await affiliate.set_custom_slug(301, "x")
        self.assertFalse(ok)

        # Rainy: запрещенные спецсимволы
        ok, msg = await affiliate.set_custom_slug(301, "my cool channel!")
        self.assertFalse(ok)

        # Rainy: только цифры запрещены
        ok, msg = await affiliate.set_custom_slug(301, "999888")
        self.assertFalse(ok)

        # Rainy: уже занятый слаг другим партнером
        ok, msg = await affiliate.set_custom_slug(301, "crypto_insider")
        self.assertFalse(ok)

        # Sunny: корректный кастомный слаг (с ref_ или без)
        ok, clean_slug = await affiliate.set_custom_slug(301, "ref_vip_alpha_trade")
        self.assertTrue(ok)
        self.assertEqual(clean_slug, "vip_alpha_trade")

    async def test_resolve_referrer_deep_link_codes(self):
        """Проверка разрешения deep-link кодов в user_id реферера."""
        await db.register_or_get_partner(401, partner_code="whale_radar")

        # Прямой ID и ref_ID
        self.assertEqual(await db.resolve_referrer_code("401"), 401)
        self.assertEqual(await db.resolve_referrer_code("ref_401"), 401)

        # Слаг и ref_слаг (включая нечувствительность к регистру)
        self.assertEqual(await db.resolve_referrer_code("whale_radar"), 401)
        self.assertEqual(await db.resolve_referrer_code("ref_whale_radar"), 401)
        self.assertEqual(await db.resolve_referrer_code("REF_WHALE_RADAR"), 401)

        # Несуществующий код
        self.assertIsNone(await db.resolve_referrer_code("unknown_slug_404"))
        self.assertIsNone(await db.resolve_referrer_code(None))

    async def test_dual_currency_commission_accounting(self):
        """Sunny Day: раздельный учет комиссий в Stars (XTR) и Рублях (RUB)."""
        partner_id = 501
        buyer_id = 502

        await db.register_or_get_partner(partner_id, partner_code="pro_trader", commission_rate=0.30)
        await db.get_or_create_user(buyer_id, "buyer", "Buyer", referrer_id=partner_id)

        # 1. Покупка за Stars (150 ⭐ -> 45 ⭐)
        res_xtr = await affiliate.process_payment_commission(
            payment_id=1, buyer_user_id=buyer_id, amount=150, currency="XTR", tariff_key="sub_1m"
        )
        self.assertIsNotNone(res_xtr)
        self.assertEqual(res_xtr["commission"], 45)
        self.assertEqual(res_xtr["currency"], "XTR")

        p = await db.get_partner(partner_id)
        self.assertEqual(p["balance_stars"], 45)
        self.assertEqual(p["balance_rub"], 0)

        # 2. Покупка за рубли СБП (1200 ₽ -> 360 ₽)
        res_rub = await affiliate.process_payment_commission(
            payment_id=2, buyer_user_id=buyer_id, amount=1200, currency="RUB", tariff_key="sub_3m"
        )
        self.assertIsNotNone(res_rub)
        self.assertEqual(res_rub["commission"], 360)
        self.assertEqual(res_rub["currency"], "RUB")

        p_updated = await db.get_partner(partner_id)
        self.assertEqual(p_updated["balance_stars"], 45)
        self.assertEqual(p_updated["balance_rub"], 360)
        self.assertEqual(p_updated["total_earned_rub"], 360)

    async def test_payout_lifecycle_with_refund_on_reject(self):
        """Sunny & Rainy: жизненный цикл выплаты, резервирование и возврат средств при отклонении."""
        partner_id = 601
        await db.register_or_get_partner(partner_id, partner_code="p_601")

        # Пополняем баланс партнера на 500 RUB
        await db.record_affiliate_earning(partner_id, 999, 10, "sub_1m", 1500, 500, "RUB")

        # Rainy: Попытка вывести меньше минимума (50 ₽)
        ok, msg, _ = await affiliate.request_payout(partner_id, 30, "RUB", "Реквизиты")
        self.assertFalse(ok)
        self.assertIn("Минимальная", msg)

        # Rainy: Попытка вывести больше текущего баланса
        ok, msg, _ = await affiliate.request_payout(partner_id, 9999, "RUB", "Реквизиты")
        self.assertFalse(ok)
        self.assertIn("Недостаточно", msg)

        # Sunny: Успешная заявка на 300 RUB -> баланс резервируется
        ok, msg, payout_id = await affiliate.request_payout(partner_id, 300, "RUB", "СБП: +79991112233 Т-Банк")
        self.assertTrue(ok)
        p = await db.get_partner(partner_id)
        self.assertEqual(p["balance_rub"], 200, "300 RUB должны списаться в резерв заявки")

        # Админ отклоняет заявку -> средства ДОЛЖНЫ вернуться на баланс
        ok_rej, _, _ = await affiliate.reject_payout(payout_id, "Некорректный номер телефона")
        self.assertTrue(ok_rej)
        p_refund = await db.get_partner(partner_id)
        self.assertEqual(p_refund["balance_rub"], 500, "Средства должны вернуться на баланс после отклонения")

        # Новая заявка и одобрение админом
        ok_new, _, new_payout_id = await affiliate.request_payout(partner_id, 400, "RUB", "СБП: +79990001122 Сбер")
        self.assertTrue(ok_new)
        ok_app, _, req_app = await affiliate.approve_payout(new_payout_id)
        self.assertTrue(ok_app)

        p_final = await db.get_partner(partner_id)
        self.assertEqual(p_final["balance_rub"], 100)
        req_rec = await db.get_payout_request(new_payout_id)
        self.assertEqual(req_rec["status"], "approved")
        self.assertIsNotNone(req_rec["processed_at"])


# ==============================================================================
# SUITE 5: Traffic Funnel Generators (Marketing Copy & Viral Scripts)
# ==============================================================================
class TestTrafficFunnelGenerators(unittest.IsolatedAsyncioTestCase):
    """Проверка генерации рекламных постов, сценариев Reels/Shorts и интеграции с генератором видео."""

    def test_promo_channel_posts_generation(self):
        """Проверка генерации рекламных креативов для Telegram-каналов."""
        ref_link = "https://t.me/CryptoRadarBot?start=ref_alpha"
        posts = traffic_funnel.get_partner_channel_posts(ref_link, "CryptoRadar Pro")

        self.assertGreaterEqual(len(posts), 4)
        for post in posts:
            self.assertIn("title", post)
            self.assertIn("category", post)
            self.assertIn("text", post)
            self.assertIn(ref_link, post["text"], "Каждый промо-пост обязан содержать реф-ссылку")
            self.assertIn("CryptoRadar Pro", post["text"])

    def test_viral_reels_scripts_structure(self):
        """Проверка структуры 30-секундных вирусных видео-сценариев."""
        scripts = traffic_funnel.get_viral_video_scripts("CryptoRadarBot", "alpha")
        self.assertGreaterEqual(len(scripts), 3)

        for script in scripts:
            self.assertIn("title", script)
            self.assertIn("target_format", script)
            self.assertIn("hook", script)
            self.assertIn("body", script)
            self.assertIn("climax", script)
            self.assertIn("cta", script)

            # Проверка наличия тайминга и визуала во всех блоках
            for block in ("hook", "body", "climax", "cta"):
                self.assertIn("timing", script[block])
                self.assertIn("visual", script[block])
                self.assertIn("voiceover", script[block])

    async def test_branded_reel_generation_integration(self):
        """Проверка интеграции traffic_funnel с модулем генерации видео generate_reel."""
        with patch("generate_reel.generate_reel", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "videos/mocked_reel.mp4"
            output_path = await traffic_funnel.generate_branded_teaser_reel(
                bot_username="test_bot",
                channel_tag="@crypto_whale",
                symbol="BTCUSDT",
                partner_code="slug_777"
            )
            self.assertEqual(output_path, "videos/mocked_reel.mp4")
            mock_gen.assert_called_once_with(
                symbol="BTCUSDT",
                bot_username="test_bot",
                channel_tag="@crypto_whale",
                output_filename="reel_slug_777_btcusdt.mp4"
            )


# ==============================================================================
# SUITE 6: Telegram Bot Routers & Keyboards (WebAppInfo & Inline Buttons)
# ==============================================================================
class TestTelegramBotUIAndRouters(unittest.TestCase):
    """Проверка структуры клавиатур (WebAppInfo, InlineButtons) и регистрации всех роутеров бота."""

    def test_keyboards_webappinfo_and_navigation(self):
        """Проверка наличия кнопки WebAppInfo в главном меню и выделенной клавиатуре."""
        # Главное меню пользователя
        main_user = kb.get_main_menu(is_admin=False)
        webapp_btn_user = next(
            (b for row in main_user.inline_keyboard for b in row if b.web_app and isinstance(b.web_app, WebAppInfo)),
            None
        )
        self.assertIsNotNone(webapp_btn_user, "В главном меню пользователя обязана быть кнопка запуска TMA WebApp")
        self.assertEqual(webapp_btn_user.web_app.url, kb.get_tma_url(user_id=None, is_vip=False))
        self.assertIn("api=", webapp_btn_user.web_app.url)

        # Главное меню VIP-пользователя
        main_vip = kb.get_main_menu(is_admin=False, user_id=12345, is_vip=True)
        webapp_btn_vip = next(
            (b for row in main_vip.inline_keyboard for b in row if b.web_app and isinstance(b.web_app, WebAppInfo)),
            None
        )
        self.assertIsNotNone(webapp_btn_vip)
        self.assertIn("PRO VIP", webapp_btn_vip.text)
        self.assertIn("vip=1", webapp_btn_vip.web_app.url)
        self.assertIn("user_id=12345", webapp_btn_vip.web_app.url)
        tariffs_btn = next((b for row in main_vip.inline_keyboard for b in row if b.callback_data == "tariffs"), None)
        self.assertIsNotNone(tariffs_btn)
        self.assertEqual(tariffs_btn.text, "⭐ Продлить VIP-доступ")

        # Главное меню администратора (содержит кнопку админки)
        main_admin = kb.get_main_menu(is_admin=True)
        admin_cbs = [b.callback_data for row in main_admin.inline_keyboard for b in row if b.callback_data]
        self.assertIn("admin_panel", admin_cbs)

        # Выделенная клавиатура /webapp
        webapp_kb = kb.get_webapp_keyboard()
        webapp_direct = next(
            (b for row in webapp_kb.inline_keyboard for b in row if b.web_app and isinstance(b.web_app, WebAppInfo)),
            None
        )
        self.assertIsNotNone(webapp_direct)

    def test_ai_and_analysis_keyboards(self):
        """Проверка кнопок AI-прогноза и экспресс-анализа."""
        res_kb = kb.get_analysis_result_keyboard("BTCUSDT")
        res_cbs = [b.callback_data for row in res_kb.inline_keyboard for b in row if b.callback_data]
        self.assertIn("ai_forecast_BTCUSDT", res_cbs)

        ai_kb = kb.get_ai_forecast_keyboard("BTCUSDT")
        ai_cbs = [b.callback_data for row in ai_kb.inline_keyboard for b in row if b.callback_data]
        self.assertIn("ai_forecast_BTCUSDT", ai_cbs)
        self.assertIn("analyze_BTCUSDT", ai_cbs)
        self.assertIn("coin_select", ai_cbs)
        self.assertIn("main_menu", ai_cbs)

    def test_partner_and_admin_keyboards(self):
        """Проверка кнопок партнерского кабинета и админ-панели."""
        p_kb = kb.get_partner_dashboard_keyboard()
        p_cbs = [b.callback_data for row in p_kb.inline_keyboard for b in row if b.callback_data]
        self.assertIn("partner_payout_select", p_cbs)
        self.assertIn("partner_promo_posts", p_cbs)
        self.assertIn("partner_promo_reels", p_cbs)
        self.assertIn("partner_gen_reel", p_cbs)
        self.assertIn("partner_set_slug", p_cbs)

        adm_p_kb = kb.get_admin_partners_keyboard(has_pending=True)
        adm_cbs = [b.callback_data for row in adm_p_kb.inline_keyboard for b in row if b.callback_data]
        self.assertIn("admin_payouts_list", adm_cbs)

    def test_bot_dispatcher_router_registration(self):
        """Проверка регистрации всех 4 роутеров в Dispatcher и наличия обработчиков ключевых команд."""
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(admin.router)
        dp.include_router(payments.router)
        dp.include_router(vip_services.router)
        dp.include_router(user.router)

        # Проверка включенных роутеров
        self.assertEqual(len(dp.sub_routers), 4)

        # Собираем зарегистрированные команды со всех роутеров
        registered_commands = set()
        for r in dp.sub_routers:
            for handler in r.message.handlers:
                for f in handler.filters:
                    # Извлекаем команды из Command / CommandStart фильтров
                    cb = getattr(f, "callback", None)
                    if cb and hasattr(cb, "commands"):
                        registered_commands.update(cb.commands)

        # Проверяем наличие критически важных команд
        expected_cmds = {"start", "webapp", "app", "help", "forecast", "ai", "partner", "affiliate", "leaderboard", "top"}
        self.assertTrue(
            expected_cmds.issubset(registered_commands),
            f"Не все команды зарегистрированы в роутерах. Ожидалось: {expected_cmds}, Найдено: {registered_commands}"
        )


# ==============================================================================
# SUITE 7: End-to-End Complete User & Monetization Lifecycle Simulation
# ==============================================================================
class TestEndToEndSaaSLifecycle(BaseSaaSTestCase):
    """
    Полная симуляция сквозного коммерческого сценария SaaS:
    1. Партнер регистрирует кастомный реф-код 'crypto_hub'.
    2. Новый пользователь переходит по ссылке /start ref_crypto_hub.
    3. Пользователь обращается к WebApp API (/api/user-status, /api/market-overview).
    4. Пользователь запрашивает глубокий AI-прогноз (/api/ai-forecast).
    5. Пользователь покупает VIP-подписку через Telegram Stars (150 ⭐).
    6. Движок ревшары автоматически начисляет 30% (45 ⭐) партнеру.
    7. Партнер запрашивает вывод средств -> администратор одобряет выплату.
    """

    async def test_complete_saas_monetization_flow(self):
        partner_id = 999111
        buyer_id = 999222

        # 1. Регистрация B2B-партнера с брендированным слагом
        await db.register_or_get_partner(partner_id, partner_code="partner_init")
        ok, slug = await affiliate.set_custom_slug(partner_id, "crypto_hub")
        self.assertTrue(ok)
        self.assertEqual(slug, "crypto_hub")

        # 2. Переход нового пользователя по deep link /start ref_crypto_hub
        resolved_ref = await db.resolve_referrer_code("ref_crypto_hub")
        self.assertEqual(resolved_ref, partner_id)

        buyer = await db.get_or_create_user(buyer_id, "alex_trader", "Alex", referrer_id=resolved_ref)
        self.assertEqual(buyer["referrer_id"], partner_id)

        # 3. Пользователь открывает WebApp (проверяем Web API статус)
        app = web_server.create_app()
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            # Статус до покупки (не VIP)
            resp_status_before = await client.get(f"/api/user-status?user_id={buyer_id}")
            self.assertEqual(resp_status_before.status, 200)
            status_before = await resp_status_before.json()
            self.assertFalse(status_before["user"]["is_vip"])

            # 4. Пользователь запрашивает AI-прогноз по BTC
            resp_ai = await client.get("/api/ai-forecast?symbol=BTC")
            self.assertEqual(resp_ai.status, 200)
            ai_data = await resp_ai.json()
            self.assertEqual(ai_data["status"], "success")
            self.assertIn("bias", ai_data)
        finally:
            await client.close()

        # 5. Пользователь покупает VIP (sub_3m за 350 Stars)
        pay_id = await db.record_payment(buyer_id, "sub_3m", 350, "XTR", "approved")
        await db.add_subscription_days(buyer_id, 90)
        self.assertTrue(await db.is_sub_active(buyer_id))

        # 6. Срабатывание автоматического начисления 30% rev-share партнеру
        commission_result = await affiliate.process_payment_commission(
            payment_id=pay_id,
            buyer_user_id=buyer_id,
            amount=350,
            currency="XTR",
            tariff_key="sub_3m"
        )
        self.assertIsNotNone(commission_result)
        self.assertEqual(commission_result["commission"], 105)

        # Партнер проверяет дашборд
        dashboard = await affiliate.get_partner_dashboard(partner_id, "CryptoRadarBot")
        self.assertEqual(dashboard["total_traders"], 1)
        self.assertEqual(dashboard["active_vips"], 1)
        self.assertEqual(dashboard["balance_stars"], 105)
        self.assertEqual(dashboard["total_earned_stars"], 105)
        self.assertIn("ref_crypto_hub", dashboard["custom_link"])

        # 7. Партнер запрашивает вывод вознаграждения (100 Stars >= MIN_PAYOUT_STARS 50)
        ok_payout, _, payout_id = await affiliate.request_payout(partner_id, 100, "XTR", "@alex_ton_wallet")
        self.assertTrue(ok_payout)

        # Баланс партнера после создания заявки становится 5 Stars (105 - 100 = 5)
        p_after_req = await db.get_partner(partner_id)
        self.assertEqual(p_after_req["balance_stars"], 5)

        # Администратор одобряет заявку на вывод
        ok_app, _, _ = await affiliate.approve_payout(payout_id)
        self.assertTrue(ok_app)

        payout_rec = await db.get_payout_request(payout_id)
        self.assertEqual(payout_rec["status"], "approved")
        self.assertIsNotNone(payout_rec["processed_at"])


class TestNotionCommandCenterSync(BaseSaaSTestCase):
    """Тестирование модуля синхронизации аналитики SaaS с Notion Command Center."""

    async def test_live_metrics_extraction(self):
        # 1. Создаем тестовых пользователей
        u1 = await db.get_or_create_user(1001, "trader_alice", "Alice")
        u2 = await db.get_or_create_user(1002, "trader_bob", "Bob")
        u3 = await db.get_or_create_user(1003, "trader_charlie", "Charlie")

        # Назначаем VIP подписку u1 и u2
        await db.add_subscription_days(1001, 30)
        await db.add_subscription_days(1002, 30)

        # 2. Создаем платежи
        await db.record_payment(1001, "sub_1m", 150, "XTR", "approved")
        await db.record_payment(1002, "sub_3m", 1200, "RUB", "approved")

        # 3. Регистрируем B2B партнера
        p = await db.register_or_get_partner(2001, "whale_channel", "Crypto Whale Alert", "@whale_alert", 0.30)
        await db.record_affiliate_earning(2001, 1001, 1, "sub_1m", 150, 45, "XTR")
        await db.record_affiliate_earning(2001, 1002, 2, "sub_3m", 1200, 360, "RUB")

        # 4. Создаем заявку на выплату
        ok_p, _, _ = await db.create_payout_request(2001, 45, "XTR", "TON: EQ...")
        self.assertTrue(ok_p)

        # 5. Извлекаем метрики
        metrics = await notion_sync.fetch_platform_metrics(TEST_DB_PATH)

        expected_admin = 1 if config.ADMIN_ID else 0
        self.assertEqual(metrics["total_users"], 3 + expected_admin)
        self.assertEqual(metrics["active_subs"], 2 + expected_admin)
        self.assertEqual(metrics["stars_revenue"], 150)
        self.assertEqual(metrics["rub_revenue"], 1200)
        self.assertEqual(metrics["revenue_24h_stars"], 150)
        self.assertEqual(metrics["revenue_24h_rub"], 1200)
        self.assertEqual(metrics["total_partners"], 1)
        self.assertEqual(metrics["affiliate_stars"], 45)
        self.assertEqual(metrics["affiliate_rub"], 360)
        self.assertEqual(metrics["pending_payout_count"], 1)
        self.assertEqual(metrics["pending_payout_stars"], 45)

    def test_notion_markdown_and_blocks_format(self):
        sample_metrics = {
            "total_users": 100,
            "active_subs": 25,
            "stars_revenue": 5000,
            "rub_revenue": 30000,
            "revenue_24h_stars": 350,
            "revenue_24h_rub": 2500,
            "total_partners": 5,
            "affiliate_stars": 1500,
            "affiliate_rub": 9000,
            "pending_payout_count": 2,
            "conversion_rate": 25.0,
            "revenue_24h_usd": 34.78,
            "total_estimated_usd": 433.33,
            "timestamp_utc": "2026-11-22 18:00:00 UTC",
        }

        # Тест Markdown Callout
        md = notion_sync.format_notion_callout_markdown(sample_metrics)
        self.assertIn('<callout icon="⚡" color="green_bg">', md)
        self.assertIn("100 traders", md)
        self.assertIn("25 subscribers", md)
        self.assertIn("5000 ⭐ / 30000 ₽", md)
        self.assertIn("services.notion_sync", md)

        # Тест REST API блоков
        blocks = notion_sync.format_notion_blocks_json(sample_metrics)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "callout")
        self.assertEqual(blocks[0]["callout"]["icon"]["emoji"], "⚡")

    async def test_notion_sync_service_cycle(self):
        from pathlib import Path
        temp_state_file = Path("test_notion_sync_state.json")
        if temp_state_file.exists():
            temp_state_file.unlink()

        try:
            service = notion_sync.NotionSyncService(
                page_id="41086ecf3dff80e28640e5a0071f5453",
                db_path=TEST_DB_PATH,
                state_file=temp_state_file,
            )
            result = await service.sync()
            self.assertTrue(result["success"])
            self.assertEqual(result["page_id"], "41086ecf3dff80e28640e5a0071f5453")
            self.assertTrue(temp_state_file.exists())

            # Проверяем содержимое закешированного состояния
            with open(temp_state_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["status"], "synced_local")
            self.assertIn("metrics", saved)
        finally:
            if temp_state_file.exists():
                temp_state_file.unlink()


# ==============================================================================
# CLI RUNNER & PRETTY OUTPUT
# ==============================================================================
def run_unified_saas_test_suite():
    print("\n" + "=" * 80)
    print("🚀  CRYPTORADAR SAAS PLATFORM — UNIFIED AUTOMATED TEST SUITE")
    print("=" * 80)
    print(f"📁 Workspace: {os.path.abspath('.')}")
    print(f"⚙️  Database Isolation: {TEST_DB_PATH} (Production DB untouched)")
    print("=" * 80 + "\n")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suites_to_load = [
        TestDatabaseAndRelations,
        TestWebServerAndAPIEndpoints,
        TestTechnicalAnalysisAndAIEngine,
        TestAffiliateRevShareEngine,
        TestTrafficFunnelGenerators,
        TestTelegramBotUIAndRouters,
        TestEndToEndSaaSLifecycle,
        TestNotionCommandCenterSync,
    ]


    for s in suites_to_load:
        suite.addTests(loader.loadTestsFromTestCase(s))

    runner = unittest.TextTestRunner(verbosity=2)
    start_time = time.time()
    result = runner.run(suite)
    elapsed = time.time() - start_time

    print("\n" + "=" * 80)
    if result.wasSuccessful():
        print(f"🎉 100% PASS! ALL {result.testsRun} TESTS COMPLETED WITH 0 FAILURES (Elapsed: {elapsed:.2f}s)")
        print("=" * 80 + "\n")
        return 0
    else:
        print(f"❌ TEST SUITE FAILED: {len(result.failures)} failures, {len(result.errors)} errors out of {result.testsRun} tests.")
        print("=" * 80 + "\n")
        return 1


if __name__ == "__main__":
    exit_code = run_unified_saas_test_suite()
    sys.exit(exit_code)
