import os
import shutil
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import config
import database as db
import keyboards as kb
from services import affiliate, traffic_funnel
import generate_reel

TEST_DB = "test_bot_database.db"

class TestAffiliateAndTrafficFunnel(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Используем отдельную временную базу для тестов
        self.original_db = db.DB_PATH
        db.DB_PATH = TEST_DB
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        await db.init_db()

    async def asyncTearDown(self):
        db.DB_PATH = self.original_db
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except Exception:
                pass

    async def test_partner_schema_and_registration(self):
        """Проверка создания партнера и схемы БД."""
        partner = await db.register_or_get_partner(
            user_id=111222,
            partner_code="alpha_trade",
            channel_name="Alpha Crypto",
            channel_link="https://t.me/alpha_crypto",
            commission_rate=0.30
        )
        self.assertEqual(partner["user_id"], 111222)
        self.assertEqual(partner["partner_code"], "alpha_trade")
        self.assertEqual(partner["commission_rate"], 0.30)
        self.assertEqual(partner["balance_stars"], 0)
        self.assertEqual(partner["balance_rub"], 0)
        self.assertEqual(partner["total_earned_stars"], 0)
        self.assertEqual(partner["total_earned_rub"], 0)

        # Повторный вызов возвращает существующего
        p2 = await db.register_or_get_partner(user_id=111222)
        self.assertEqual(p2["partner_code"], "alpha_trade")

    async def test_partner_slug_validation_and_update(self):
        """Проверка валидации и установки кастомного слага."""
        await db.register_or_get_partner(1001, partner_code="partner_1001")
        await db.register_or_get_partner(1002, partner_code="taken_code")

        # Слишком короткий
        ok, msg = await affiliate.set_custom_slug(1001, "ab")
        self.assertFalse(ok)

        # Недопустимые символы
        ok, msg = await affiliate.set_custom_slug(1001, "hello world!")
        self.assertFalse(ok)

        # Только цифры запрещены
        ok, msg = await affiliate.set_custom_slug(1001, "1234567")
        self.assertFalse(ok)

        # Уже занятый код
        ok, msg = await affiliate.set_custom_slug(1001, "taken_code")
        self.assertFalse(ok)

        # Корректный код (с префиксом ref_ или без)
        ok, code = await affiliate.set_custom_slug(1001, "ref_my_crypto_channel")
        self.assertTrue(ok)
        self.assertEqual(code, "my_crypto_channel")

        p = await db.get_partner(1001)
        self.assertEqual(p["partner_code"], "my_crypto_channel")

    async def test_resolve_referrer_code(self):
        """Проверка разрешения реферального кода: ID, ref_ID, slug, ref_slug."""
        await db.register_or_get_partner(777, partner_code="whale_insider")

        # Числовой ID
        self.assertEqual(await db.resolve_referrer_code("777"), 777)
        self.assertEqual(await db.resolve_referrer_code("ref_777"), 777)

        # Кастомный slug
        self.assertEqual(await db.resolve_referrer_code("whale_insider"), 777)
        self.assertEqual(await db.resolve_referrer_code("ref_whale_insider"), 777)
        self.assertEqual(await db.resolve_referrer_code("REF_WHALE_INSIDER"), 777)

        # Несуществующий код
        self.assertIsNone(await db.resolve_referrer_code("unknown_slug_123"))
        self.assertIsNone(await db.resolve_referrer_code(None))

    def test_commission_calculation(self):
        """Проверка математики 30% rev-share."""
        self.assertEqual(affiliate.calculate_commission(150, 0.30), 45)
        self.assertEqual(affiliate.calculate_commission(350, 0.30), 105)
        self.assertEqual(affiliate.calculate_commission(1200, 0.30), 360)
        self.assertEqual(affiliate.calculate_commission(3500, 0.30), 1050)
        self.assertEqual(affiliate.calculate_commission(1, 0.30), 1)
        self.assertEqual(affiliate.calculate_commission(0, 0.30), 0)

    async def test_process_payment_commission_stars_and_rub(self):
        """Проверка начисления комиссии партнеру при оплатах Stars и RUB."""
        partner_id = 5001
        buyer_id = 5002
        
        # Создаем реферера и покупателя
        await db.register_or_get_partner(partner_id, partner_code="top_channel", commission_rate=0.30)
        await db.get_or_create_user(buyer_id, "buyer", "Buyer", referrer_id=partner_id)

        # 1. Оплата через Stars: 150 ⭐ -> 30% = 45 ⭐
        res_stars = await affiliate.process_payment_commission(
            payment_id=1,
            buyer_user_id=buyer_id,
            amount=150,
            currency="XTR",
            tariff_key="sub_1m"
        )
        self.assertIsNotNone(res_stars)
        self.assertEqual(res_stars["commission"], 45)
        self.assertEqual(res_stars["currency"], "XTR")

        p = await db.get_partner(partner_id)
        self.assertEqual(p["balance_stars"], 45)
        self.assertEqual(p["total_earned_stars"], 45)
        self.assertEqual(p["balance_rub"], 0)

        # 2. Оплата через СБП/Рубли: 1200 ₽ -> 30% = 360 ₽
        res_rub = await affiliate.process_payment_commission(
            payment_id=2,
            buyer_user_id=buyer_id,
            amount=1200,
            currency="RUB",
            tariff_key="sub_3m"
        )
        self.assertIsNotNone(res_rub)
        self.assertEqual(res_rub["commission"], 360)
        self.assertEqual(res_rub["currency"], "RUB")

        p = await db.get_partner(partner_id)
        self.assertEqual(p["balance_stars"], 45)
        self.assertEqual(p["balance_rub"], 360)
        self.assertEqual(p["total_earned_rub"], 360)

    async def test_partner_dashboard_metrics(self):
        """Проверка расчета показателей дашборда (привлеченные трейдеры, активные VIP, балансы)."""
        partner_id = 6001
        await db.register_or_get_partner(partner_id, partner_code="crypto_hub")

        # Приглашаем 3 пользователей
        await db.get_or_create_user(6002, "u2", "User 2", referrer_id=partner_id)
        await db.get_or_create_user(6003, "u3", "User 3", referrer_id=partner_id)
        await db.get_or_create_user(6004, "u4", "User 4", referrer_id=partner_id)

        # Двоим даем активную подписку
        await db.add_subscription_days(6002, 30)
        await db.add_subscription_days(6003, 90)

        # Начисляем комиссию
        await affiliate.process_payment_commission(10, 6002, 150, "XTR", "sub_1m")

        dashboard = await affiliate.get_partner_dashboard(partner_id, "my_test_bot")
        self.assertEqual(dashboard["total_traders"], 3)
        self.assertEqual(dashboard["active_vips"], 2)
        self.assertEqual(dashboard["balance_stars"], 45)
        self.assertEqual(dashboard["rate_percent"], 30)
        self.assertIn("https://t.me/my_test_bot?start=ref_6001", dashboard["standard_link"])
        self.assertIn("https://t.me/my_test_bot?start=ref_crypto_hub", dashboard["custom_link"])

        text = affiliate.format_dashboard_text(dashboard)
        self.assertIn("30% Rev-Share", text)
        self.assertIn("Привлечено трейдеров: <b>3</b>", text)
        self.assertIn("Активных VIP-подписчиков: <b>2</b>", text)
        self.assertIn("45 ⭐", text)

    async def test_payout_request_and_admin_workflow(self):
        """Проверка жизненного цикла выплаты: запрос, проверка баланса, одобрение и отклонение с возвратом."""
        partner_id = 7001
        await db.register_or_get_partner(partner_id, partner_code="partner_7001")
        
        # Начисляем баланс: 500 RUB и 200 XTR
        await db.record_affiliate_earning(partner_id, 999, 1, "sub_1m", 1500, 500, "RUB")
        await db.record_affiliate_earning(partner_id, 999, 2, "sub_1m", 600, 200, "XTR")

        # 1. Попытка вывести меньше минимума
        ok, msg, _ = await affiliate.request_payout(partner_id, 40, "RUB", "Карта 1234")
        self.assertFalse(ok)
        self.assertIn("Минимальная сумма", msg)

        # 2. Попытка вывести больше баланса
        ok, msg, _ = await affiliate.request_payout(partner_id, 1000, "RUB", "Карта 1234")
        self.assertFalse(ok)
        self.assertIn("Недостаточно средств", msg)

        # 3. Успешный запрос на вывод 300 RUB
        ok, msg, payout_id = await affiliate.request_payout(partner_id, 300, "RUB", "СБП: +79991234567 Т-Банк")
        self.assertTrue(ok)
        self.assertIsNotNone(payout_id)

        # Баланс уменьшился на 300
        p = await db.get_partner(partner_id)
        self.assertEqual(p["balance_rub"], 200)

        # Проверка в очереди админа
        pending = await db.get_pending_payout_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], payout_id)
        self.assertEqual(pending[0]["amount"], 300)

        # 4. Администратор отклоняет заявку -> средства возвращаются на баланс!
        ok, msg, req = await affiliate.reject_payout(payout_id, "Неверные реквизиты")
        self.assertTrue(ok)

        p_refunded = await db.get_partner(partner_id)
        self.assertEqual(p_refunded["balance_rub"], 500)  # 200 + 300 = 500

        # 5. Новый запрос и одобрение администратором
        ok, msg, new_payout_id = await affiliate.request_payout(partner_id, 400, "RUB", "СБП: +79991234567 Сбер")
        self.assertTrue(ok)
        
        ok_app, msg_app, req_app = await affiliate.approve_payout(new_payout_id)
        self.assertTrue(ok_app)

        p_after = await db.get_partner(partner_id)
        self.assertEqual(p_after["balance_rub"], 100)

        req_final = await db.get_payout_request(new_payout_id)
        self.assertEqual(req_final["status"], "approved")
        self.assertIsNotNone(req_final["processed_at"])

    def test_traffic_funnel_promo_posts_and_scripts(self):
        """Проверка генерации вирусных постов и Reels-сценариев."""
        ref_link = "https://t.me/CryptoRadarBot?start=ref_alpha_channel"
        posts = traffic_funnel.get_partner_channel_posts(ref_link, "CryptoRadar Pro")
        self.assertGreaterEqual(len(posts), 4)

        for p in posts:
            self.assertIn("title", p)
            self.assertIn("text", p)
            self.assertIn(ref_link, p["text"])
            self.assertIn("CryptoRadar Pro", p["text"])

        scripts = traffic_funnel.get_viral_video_scripts("CryptoRadarBot", "alpha_channel")
        self.assertGreaterEqual(len(scripts), 3)

        for s in scripts:
            self.assertIn("hook", s)
            self.assertIn("body", s)
            self.assertIn("climax", s)
            self.assertIn("cta", s)
            self.assertIn("@CryptoRadarBot", s["cta"]["visual"])

    async def test_traffic_funnel_reel_integration(self):
        """Проверка интеграции traffic_funnel с генератором видео Reels."""
        with patch("generate_reel.generate_reel", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "videos/reel_test.mp4"
            path = await traffic_funnel.generate_branded_teaser_reel(
                bot_username="test_bot",
                channel_tag="@test_channel",
                symbol="BTCUSDT",
                partner_code="slug_123"
            )
            self.assertEqual(path, "videos/reel_test.mp4")
            mock_gen.assert_called_once_with(
                symbol="BTCUSDT",
                bot_username="test_bot",
                channel_tag="@test_channel",
                output_filename="reel_slug_123_btcusdt.mp4"
            )

    async def test_admin_partners_summary(self):
        """Проверка агрегированной статистики для админ-панели."""
        await db.register_or_get_partner(8001, partner_code="p1")
        await db.register_or_get_partner(8002, partner_code="p2")

        await db.record_affiliate_earning(8001, 1, 1, "sub_1m", 150, 45, "XTR")
        await db.record_affiliate_earning(8002, 2, 2, "sub_3m", 1200, 360, "RUB")
        
        # Создаем заявку на выплату
        await affiliate.request_payout(8002, 200, "RUB", "Реквизиты")

        summary = await db.get_admin_partners_summary()
        self.assertGreaterEqual(summary["total_partners"], 2)
        self.assertEqual(summary["affiliate_stars"], 45)
        self.assertEqual(summary["affiliate_rub"], 360)
        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual(summary["pending_rub"], 200)

    def test_keyboards_structure(self):
        """Проверка кнопок партнерского кабинета и админки."""
        menu = kb.get_main_menu(is_admin=True)
        all_cb = [btn.callback_data for row in menu.inline_keyboard for btn in row if btn.callback_data]
        self.assertIn("partner_dashboard", all_cb)
        self.assertIn("admin_panel", all_cb)

        partner_kb = kb.get_partner_dashboard_keyboard()
        partner_cbs = [btn.callback_data for row in partner_kb.inline_keyboard for btn in row if btn.callback_data]
        self.assertIn("partner_payout_select", partner_cbs)
        self.assertIn("partner_promo_posts", partner_cbs)
        self.assertIn("partner_promo_reels", partner_cbs)
        self.assertIn("partner_gen_reel", partner_cbs)
        self.assertIn("partner_set_slug", partner_cbs)

        admin_p_kb = kb.get_admin_panel()
        admin_cbs = [btn.callback_data for row in admin_p_kb.inline_keyboard for btn in row if btn.callback_data]
        self.assertIn("admin_partners", admin_cbs)

if __name__ == "__main__":
    unittest.main()
