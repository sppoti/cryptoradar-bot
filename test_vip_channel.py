import asyncio
import datetime
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import config
import database as db
import keyboards as kb
from services import vip_channel
from handlers import payments, admin, user, vip_services
from aiogram import Bot
from aiogram.types import (
    Message, CallbackQuery, ChatJoinRequest, Chat, User as TgUser,
    ChatMemberAdministrator, ChatMemberMember, InlineKeyboardMarkup
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

TEST_DB = "test_vip_channel_db.db"


def make_mock_callback(user_id: int = 123) -> MagicMock:
    cb = MagicMock()
    cb.__class__ = CallbackQuery
    cb.from_user.id = user_id
    cb.from_user.username = "testuser"
    cb.from_user.first_name = "Test"
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


class TestVipChannelSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_db = db.DB_PATH
        db.DB_PATH = TEST_DB
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        await db.init_db()

        self.storage = MemoryStorage()
        self.original_vip_channel_id = config.VIP_CHANNEL_ID
        self.original_channel_id = config.CHANNEL_ID
        self.original_admin_id = config.ADMIN_ID
        self.original_vip_link = config.VIP_LINK

        config.VIP_CHANNEL_ID = -1001234567890
        config.CHANNEL_ID = "@cryptoradar_live777"
        config.ADMIN_ID = 999888
        config.VIP_LINK = "https://t.me/+static_fallback_link"

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
        config.VIP_LINK = self.original_vip_link

    def get_fsm_context(self, user_id: int = 12345) -> FSMContext:
        key = StorageKey(bot_id=123456789, chat_id=user_id, user_id=user_id)
        return FSMContext(storage=self.storage, key=key)

    # =========================================================================
    # 1. ТЕСТЫ БАЗЫ ДАННЫХ (database.py)
    # =========================================================================

    async def test_db_record_vip_channel_join_and_get_active(self):
        """Фиксация вступления в VIP-канал и получение списка активных участников."""
        await db.get_or_create_user(1001, "trader1", "Trader One")
        await db.record_vip_channel_join(1001)

        self.assertTrue(await db.is_vip_channel_member(1001))
        active_members = await db.get_active_vip_channel_members()
        self.assertEqual(len(active_members), 1)
        self.assertEqual(active_members[0]["user_id"], 1001)
        self.assertEqual(active_members[0]["is_active"], 1)

        # Повторный вызов обновляет joined_at/last_check (идемпотентность ON CONFLICT)
        await db.record_vip_channel_join(1001)
        active_members_after = await db.get_active_vip_channel_members()
        self.assertEqual(len(active_members_after), 1)

    async def test_db_mark_vip_channel_left(self):
        """Пометка пользователя как покинувшего / исключенного из VIP-канала."""
        await db.get_or_create_user(1002, "trader2", "Trader Two")
        await db.record_vip_channel_join(1002)
        self.assertTrue(await db.is_vip_channel_member(1002))

        await db.mark_vip_channel_left(1002)
        self.assertFalse(await db.is_vip_channel_member(1002))

        active_members = await db.get_active_vip_channel_members()
        self.assertEqual(len(active_members), 0)

        member_record = await db.get_vip_channel_member(1002)
        self.assertIsNotNone(member_record)
        self.assertEqual(member_record["is_active"], 0)

    async def test_db_get_expired_vip_members(self):
        """Получение участников VIP-канала с истекшей подпиской."""
        # 1. Пользователь с истекшей подпиской (вчера)
        await db.get_or_create_user(2001, "expired_user", "Expired")
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat()
        async with aiosqlite_conn() as conn:
            await conn.execute("UPDATE users SET sub_until = ? WHERE user_id = 2001", (yesterday,))
            await conn.commit()
        await db.record_vip_channel_join(2001)

        # 2. Пользователь без подписки (sub_until IS NULL)
        await db.get_or_create_user(2002, "no_sub_user", "NoSub")
        await db.record_vip_channel_join(2002)

        # 3. Пользователь с активной подпиской (+30 дней)
        await db.get_or_create_user(2003, "active_vip", "Active")
        await db.add_subscription_days(2003, 30)
        await db.record_vip_channel_join(2003)

        # 4. Пользователь с истекшей подпиской, но уже исключенный (is_active = 0)
        await db.get_or_create_user(2004, "already_left", "Left")
        await db.record_vip_channel_join(2004)
        await db.mark_vip_channel_left(2004)

        expired = await db.get_expired_vip_members()
        expired_ids = [m["user_id"] for m in expired]

        self.assertIn(2001, expired_ids, "Истекший пользователь должен быть в списке")
        self.assertIn(2002, expired_ids, "Пользователь без sub_until должен быть в списке")
        self.assertNotIn(2003, expired_ids, "Активный VIP пользователь НЕ должен быть в списке")
        self.assertNotIn(2004, expired_ids, "Уже исключенный пользователь НЕ должен быть в списке")

    # =========================================================================
    # 2. ТЕСТЫ СЕРВИСА VIP-КАНАЛА (services/vip_channel.py)
    # =========================================================================

    def test_is_vip_channel_configured(self):
        """Проверка условий включения динамического VIP-канала."""
        # Настроен и отличается от CHANNEL_ID
        config.VIP_CHANNEL_ID = -1001234567890
        config.CHANNEL_ID = "@my_public_channel"
        self.assertTrue(vip_channel.is_vip_channel_configured())

        # Пустой VIP_CHANNEL_ID
        config.VIP_CHANNEL_ID = ""
        self.assertFalse(vip_channel.is_vip_channel_configured())

        # VIP_CHANNEL_ID равен CHANNEL_ID (обратная совместимость)
        config.VIP_CHANNEL_ID = -1001234567890
        config.CHANNEL_ID = -1001234567890
        self.assertFalse(vip_channel.is_vip_channel_configured())

    async def test_create_vip_invite_link_success(self):
        """Генерация одноразовой пригласительной ссылки с member_limit=1."""
        bot = MagicMock(spec=Bot)
        mock_invite = MagicMock()
        mock_invite.invite_link = "https://t.me/+unique_one_time_vip_link"
        bot.create_chat_invite_link = AsyncMock(return_value=mock_invite)

        link = await vip_channel.create_vip_invite_link(bot, user_id=777)

        self.assertEqual(link, "https://t.me/+unique_one_time_vip_link")
        bot.create_chat_invite_link.assert_called_once()
        call_kwargs = bot.create_chat_invite_link.call_args[1]
        self.assertEqual(call_kwargs["chat_id"], -1001234567890)
        self.assertEqual(call_kwargs["member_limit"], 1)
        self.assertFalse(call_kwargs["creates_join_request"])
        self.assertTrue(call_kwargs["name"].startswith("VIP_777_"))

    async def test_create_vip_invite_link_fallback_when_disabled(self):
        """При выключенном VIP_CHANNEL_ID возвращается static VIP_LINK."""
        config.VIP_CHANNEL_ID = ""
        bot = MagicMock(spec=Bot)
        link = await vip_channel.create_vip_invite_link(bot, user_id=777)
        self.assertEqual(link, config.VIP_LINK)

    async def test_create_vip_invite_link_fallback_on_error(self):
        """При ошибке API создания ссылки сервис безопасно возвращает VIP_LINK."""
        bot = MagicMock(spec=Bot)
        bot.create_chat_invite_link = AsyncMock(side_effect=Exception("Chat not found"))

        link = await vip_channel.create_vip_invite_link(bot, user_id=777)
        self.assertEqual(link, config.VIP_LINK)

    async def test_process_join_request_approves_for_vip(self):
        """Одобрение заявки на вступление (chat_join_request) для активного VIP."""
        user_id = 3001
        await db.get_or_create_user(user_id, "vip_trader", "VIP", None)
        await db.add_subscription_days(user_id, 30)

        event = MagicMock()
        event.chat.id = -1001234567890
        event.from_user.id = user_id
        event.from_user.username = "vip_trader"
        event.from_user.first_name = "VIP"

        bot = MagicMock(spec=Bot)
        bot.approve_chat_join_request = AsyncMock()
        bot.send_message = AsyncMock()

        await vip_channel.process_join_request(event, bot)

        bot.approve_chat_join_request.assert_called_once_with(chat_id=-1001234567890, user_id=user_id)
        # Пользователь зафиксирован в БД участников
        self.assertTrue(await db.is_vip_channel_member(user_id))
        # Приветственное сообщение отправлено в ЛС
        bot.send_message.assert_called_once()
        msg_text = bot.send_message.call_args[0][1]
        self.assertIn("Добро пожаловать в закрытый VIP Club", msg_text)

    async def test_process_join_request_declines_for_non_vip(self):
        """Отклонение заявки на вступление для пользователя без VIP-подписки."""
        user_id = 3002
        await db.get_or_create_user(user_id, "free_trader", "Free", None)

        event = MagicMock()
        event.chat.id = -1001234567890
        event.from_user.id = user_id
        event.from_user.username = "free_trader"
        event.from_user.first_name = "Free"

        bot = MagicMock(spec=Bot)
        bot.decline_chat_join_request = AsyncMock()
        bot.send_message = AsyncMock()

        await vip_channel.process_join_request(event, bot)

        bot.decline_chat_join_request.assert_called_once_with(chat_id=-1001234567890, user_id=user_id)
        # Пользователь НЕ зафиксирован как активный участник
        self.assertFalse(await db.is_vip_channel_member(user_id))
        # Сообщение с предложением подписки отправлено
        bot.send_message.assert_called_once()
        msg_text = bot.send_message.call_args[0][1]
        self.assertIn("Заявка в закрытый VIP-канал отклонена", msg_text)

    async def test_check_and_kick_expired_members(self):
        """Исключение пользователей с истекшей подпиской из VIP-канала."""
        user_id = 4001
        await db.get_or_create_user(user_id, "expired_guy", "Expired Guy", None)
        # Подписка истекла вчера
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat()
        async with aiosqlite_conn() as conn:
            await conn.execute("UPDATE users SET sub_until = ? WHERE user_id = ?", (yesterday, user_id))
            await conn.commit()
        await db.record_vip_channel_join(user_id)

        bot = MagicMock(spec=Bot)
        bot.ban_chat_member = AsyncMock()
        bot.unban_chat_member = AsyncMock()
        bot.send_message = AsyncMock()

        kicked = await vip_channel.check_and_kick_expired_members(bot)

        self.assertEqual(kicked, 1)
        bot.ban_chat_member.assert_called_once_with(chat_id=-1001234567890, user_id=user_id)
        bot.unban_chat_member.assert_called_once_with(chat_id=-1001234567890, user_id=user_id, only_if_banned=True)
        # В БД помечен как неактивный
        self.assertFalse(await db.is_vip_channel_member(user_id))
        # Отправлено уведомление об истечении в ЛС
        bot.send_message.assert_called_once()
        self.assertIn("Срок действия вашей VIP-подписки истек", bot.send_message.call_args[0][1])

    async def test_check_bot_channel_permissions(self):
        """Проверка прав администратора бота в VIP-канале."""
        bot = MagicMock(spec=Bot)
        bot.id = 123456789

        chat_mock = MagicMock()
        chat_mock.title = "CryptoRadar VIP Private"
        chat_mock.username = None
        chat_mock.type = "channel"
        bot.get_chat = AsyncMock(return_value=chat_mock)

        member_mock = MagicMock(spec=ChatMemberAdministrator)
        member_mock.status = "administrator"
        member_mock.can_invite_users = True
        member_mock.can_restrict_members = True
        member_mock.can_post_messages = True
        bot.get_chat_member = AsyncMock(return_value=member_mock)
        bot.get_chat_member_count = AsyncMock(return_value=42)

        res = await vip_channel.check_bot_channel_permissions(bot)

        self.assertTrue(res["ok"])
        self.assertEqual(res["channel_id"], -1001234567890)
        self.assertEqual(res["title"], "CryptoRadar VIP Private")
        self.assertTrue(res["is_admin"])
        self.assertTrue(res["can_invite_users"])
        self.assertTrue(res["can_restrict_members"])
        self.assertTrue(res["can_post_messages"])
        self.assertEqual(res["tg_members_count"], 42)

    # =========================================================================
    # 3. ТЕСТЫ ИНТЕГРАЦИИ В ХЭНДЛЕРЫ
    # =========================================================================

    async def test_successful_stars_payment_generates_dynamic_vip_link(self):
        """После успешной оплаты Stars генерируется персональная ссылка."""
        user_id = 5001
        await db.get_or_create_user(user_id, "buyer", "Buyer")

        message = MagicMock()
        message.from_user.id = user_id
        message.from_user.username = "buyer"
        message.successful_payment.total_amount = 150
        message.successful_payment.invoice_payload = f"stars_sub_1m_{user_id}"
        message.answer = AsyncMock()

        bot = MagicMock()
        message.bot = bot

        mock_invite = MagicMock()
        mock_invite.invite_link = "https://t.me/+dynamic_stars_link_123"
        bot.create_chat_invite_link = AsyncMock(return_value=mock_invite)

        with patch("services.affiliate.process_payment_commission", new=AsyncMock(return_value=None)):
            await payments.process_successful_payment(message)

        # Проверяем, что создана персональная ссылка
        bot.create_chat_invite_link.assert_called_once()
        message.answer.assert_called_once()
        answer_text = message.answer.call_args[0][0]
        self.assertIn("https://t.me/+dynamic_stars_link_123", answer_text)
        markup = message.answer.call_args[1]["reply_markup"]
        urls = [b.url for row in markup.inline_keyboard for b in row if b.url]
        self.assertIn("https://t.me/+dynamic_stars_link_123", urls)
        # Пользователь зафиксирован в базе канала
        self.assertTrue(await db.is_vip_channel_member(user_id))

    async def test_admin_grant_generates_dynamic_vip_link(self):
        """Ручная выдача подписки (/grant) генерирует персональную ссылку."""
        target_id = 6001
        await db.get_or_create_user(target_id, "lucky_user", "Lucky")

        message = MagicMock()
        message.from_user.id = config.ADMIN_ID
        message.text = f"{target_id} 30"
        message.answer = AsyncMock()

        bot = MagicMock()
        bot.send_message = AsyncMock()
        mock_invite = MagicMock()
        mock_invite.invite_link = "https://t.me/+grant_vip_link_456"
        bot.create_chat_invite_link = AsyncMock(return_value=mock_invite)
        message.bot = bot

        state = self.get_fsm_context(config.ADMIN_ID)
        await state.set_state(admin.AdminState.waiting_for_grant)

        await admin.process_grant(message, state)

        # Пользователю отправлено сообщение с персональной ссылкой
        bot.send_message.assert_called_once()
        user_sent = bot.send_message.call_args[0][1]
        self.assertIn("https://t.me/+grant_vip_link_456", user_sent)
        # В ответе админу также выведена ссылка
        message.answer.assert_called_once()
        admin_sent = message.answer.call_args[0][0]
        self.assertIn("https://t.me/+grant_vip_link_456", admin_sent)
        # Пользователь зафиксирован в базе участников VIP-канала
        self.assertTrue(await db.is_vip_channel_member(target_id))

    async def test_user_profile_shows_vip_enter_button_for_vip(self):
        """В профиле отображается кнопка '🔐 Перейти в VIP-канал' как для VIP, так и для Free."""
        user_id = 7001
        await db.get_or_create_user(user_id, "active_profile_user", "Alex")
        await db.add_subscription_days(user_id, 30)

        cb = make_mock_callback(user_id)
        bot = MagicMock()
        bot_user = TgUser(id=123, is_bot=True, first_name="Bot", username="cryptoradar_bot")
        bot.get_me = AsyncMock(return_value=bot_user)
        cb.bot = bot

        await user.cb_profile(cb)

        cb.message.edit_text.assert_called_once()
        markup = cb.message.edit_text.call_args[1]["reply_markup"]
        all_buttons = [b.text for row in markup.inline_keyboard for b in row]
        self.assertIn("🔐 Перейти в VIP-канал", all_buttons)

        # Проверка, что для неактивного пользователя кнопка также отображается в клавиатуре
        free_kb = kb.get_profile_keyboard(has_active_sub=False)
        free_buttons = [b.text for row in free_kb.inline_keyboard for b in row]
        self.assertIn("🔐 Перейти в VIP-канал", free_buttons)

    async def test_user_enter_vip_channel_generates_fresh_link_for_vip(self):
        """Нажатие '🔗 Войти в VIP-канал' генерирует свежую ссылку для VIP."""
        user_id = 7002
        await db.get_or_create_user(user_id, "vip_enter_user", "Maria")
        await db.add_subscription_days(user_id, 30)

        cb = make_mock_callback(user_id)
        bot = MagicMock()
        mock_invite = MagicMock()
        mock_invite.invite_link = "https://t.me/+fresh_user_link_789"
        bot.create_chat_invite_link = AsyncMock(return_value=mock_invite)
        cb.bot = bot

        await user.cb_enter_vip_channel(cb)

        cb.message.edit_text.assert_called_once()
        call_text = cb.message.edit_text.call_args[0][0]
        self.assertIn("https://t.me/+fresh_user_link_789", call_text)
        markup = cb.message.edit_text.call_args[1]["reply_markup"]
        urls = [b.url for row in markup.inline_keyboard for b in row if b.url]
        self.assertIn("https://t.me/+fresh_user_link_789", urls)
        # Проверяем вторую строку навигации: [Главное меню, Мой профиль]
        row2 = [b.callback_data for b in markup.inline_keyboard[1]]
        self.assertEqual(row2, ["main_menu", "profile"])

    async def test_user_enter_vip_channel_denied_for_non_vip(self):
        """Нажатие '🔗 Войти в VIP-канал' без подписки выводит предложение тарифов."""
        user_id = 7003
        await db.get_or_create_user(user_id, "non_vip_user", "Elena")

        cb = make_mock_callback(user_id)
        cb.bot = MagicMock()

        await user.cb_enter_vip_channel(cb)

        cb.message.edit_text.assert_called_once()
        call_text = cb.message.edit_text.call_args[0][0]
        self.assertIn("Доступ в закрытый VIP-канал ограничен", call_text)

    async def test_admin_can_enter_vip_channel_without_active_sub(self):
        """Администратор (ADMIN_ID) получает ссылку в VIP-канал даже без подписки в БД."""
        admin_id = config.ADMIN_ID
        await db.get_or_create_user(admin_id, "admin_user", "Admin")
        # Подписку не начисляем

        cb = make_mock_callback(admin_id)
        bot = MagicMock()
        mock_invite = MagicMock()
        mock_invite.invite_link = "https://t.me/+admin_vip_link_999"
        bot.create_chat_invite_link = AsyncMock(return_value=mock_invite)
        cb.bot = bot

        await user.cb_enter_vip_channel(cb)

        cb.message.edit_text.assert_called_once()
        call_text = cb.message.edit_text.call_args[0][0]
        self.assertIn("https://t.me/+admin_vip_link_999", call_text)
        markup = cb.message.edit_text.call_args[1]["reply_markup"]
        urls = [b.url for row in markup.inline_keyboard for b in row if b.url]
        self.assertIn("https://t.me/+admin_vip_link_999", urls)

    def test_keyboards_vip_channel_buttons(self):
        """Проверка добавления кнопки входа в VIP-канал во все требуемые клавиатуры."""
        # 1. get_main_menu
        main_menu = kb.get_main_menu()
        main_cbs = [b.callback_data for row in main_menu.inline_keyboard for b in row if b.callback_data]
        self.assertIn("enter_vip_channel", main_cbs)

        # 2. get_webapp_keyboard
        webapp_kb = kb.get_webapp_keyboard()
        webapp_cbs = [b.callback_data for row in webapp_kb.inline_keyboard for b in row if b.callback_data]
        self.assertIn("enter_vip_channel", webapp_cbs)

        # 3. get_payment_success_keyboard
        # с переданным vip_link:
        success_kb_url = kb.get_payment_success_keyboard(vip_link="https://t.me/+test_link")
        url_btns = [b for row in success_kb_url.inline_keyboard for b in row if b.url == "https://t.me/+test_link"]
        self.assertEqual(len(url_btns), 1)
        self.assertEqual(url_btns[0].text, "🔐 Перейти в VIP-канал")

        # без vip_link:
        success_kb_cb = kb.get_payment_success_keyboard()
        cb_btns = [b for row in success_kb_cb.inline_keyboard for b in row if b.callback_data == "enter_vip_channel"]
        self.assertEqual(len(cb_btns), 1)
        self.assertEqual(cb_btns[0].text, "🔐 Перейти в VIP-канал")

        # 4. get_profile_keyboard (всегда отображается)
        prof_free = kb.get_profile_keyboard(has_active_sub=False)
        self.assertIn("enter_vip_channel", [b.callback_data for row in prof_free.inline_keyboard for b in row])
        prof_active = kb.get_profile_keyboard(has_active_sub=True)
        self.assertIn("enter_vip_channel", [b.callback_data for row in prof_active.inline_keyboard for b in row])

    async def test_admin_vip_channel_status_callback(self):
        """Админ-панель: отображение статуса и прав в закрытом VIP-канале."""
        cb = make_mock_callback(config.ADMIN_ID)
        bot = MagicMock()
        bot.id = 123456789
        chat_mock = MagicMock()
        chat_mock.title = "CryptoRadar VIP Private"
        chat_mock.username = None
        chat_mock.type = "channel"
        bot.get_chat = AsyncMock(return_value=chat_mock)

        member_mock = MagicMock()
        member_mock.status = "administrator"
        member_mock.can_invite_users = True
        member_mock.can_restrict_members = True
        member_mock.can_post_messages = True
        bot.get_chat_member = AsyncMock(return_value=member_mock)
        bot.get_chat_member_count = AsyncMock(return_value=15)
        cb.bot = bot

        await admin.cb_admin_vip_channel_status(cb)

        cb.message.edit_text.assert_called_once()
        text = cb.message.edit_text.call_args[0][0]
        self.assertIn("Статус закрытого VIP-канала", text)
        self.assertIn("CryptoRadar VIP Private", text)
        self.assertIn("Администратор", text)
        self.assertIn("15", text)

    async def test_admin_kick_expired_callback(self):
        """Админ-панель: ручной запуск исключения истекших участников."""
        cb = make_mock_callback(config.ADMIN_ID)
        cb.message.answer = AsyncMock()
        bot = MagicMock()
        cb.bot = bot

        with patch("services.vip_channel.check_and_kick_expired_members", new=AsyncMock(return_value=3)):
            await admin.cb_admin_kick_expired(cb)

        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
        sent_text = cb.message.answer.call_args[0][0]
        self.assertIn("Очистка завершена!", sent_text)
        self.assertIn("3", sent_text)

    async def test_sbp_payment_approval_generates_dynamic_vip_link(self):
        """Подтверждение платежа СБП администратором генерирует персональную ссылку."""
        user_id = 8001
        await db.get_or_create_user(user_id, "sbp_buyer", "SBP Buyer")
        payment_id = await db.record_payment(user_id, "sub_1m", 150, "RUB", "pending")

        cb = make_mock_callback(config.ADMIN_ID)
        cb.data = f"adm_approve_{payment_id}"
        cb.message.caption = "Чек от пользователя"
        cb.message.edit_caption = AsyncMock()

        bot = MagicMock()
        bot.send_message = AsyncMock()
        mock_invite = MagicMock()
        mock_invite.invite_link = "https://t.me/+sbp_approved_dynamic_link"
        bot.create_chat_invite_link = AsyncMock(return_value=mock_invite)
        cb.bot = bot

        with patch("services.affiliate.process_payment_commission", new=AsyncMock(return_value=None)):
            await payments.cb_admin_approve(cb)

        # Проверяем, что создана персональная ссылка и отправлена пользователю
        bot.create_chat_invite_link.assert_called_once()
        bot.send_message.assert_called_once()
        user_msg = bot.send_message.call_args[0][1]
        self.assertIn("https://t.me/+sbp_approved_dynamic_link", user_msg)
        # Пользователь зафиксирован в базе участников VIP-канала
        self.assertTrue(await db.is_vip_channel_member(user_id))

    async def test_vip_expiry_checker_loop_cancels_cleanly(self):
        """Фоновый цикл проверки подписок запускается и корректно останавливается при отмене."""
        bot = MagicMock()
        with patch("services.vip_channel.check_and_kick_expired_members", new=AsyncMock(return_value=0)) as mock_kick:
            task = asyncio.create_task(vip_channel.vip_expiry_checker_loop(bot, interval_seconds=1))
            await asyncio.sleep(0.05)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            mock_kick.assert_called()

    async def test_vip_services_join_request_and_chat_member_handlers(self):
        """Проверка работы роутера vip_services для ChatJoinRequest и прямого входа ChatMemberUpdated."""
        event_join = MagicMock()
        event_join.chat.id = -1001234567890
        event_join.from_user.id = 9001
        bot = MagicMock()

        with patch("services.vip_channel.process_join_request", new=AsyncMock()) as mock_proc:
            await vip_services.cb_vip_join_request(event_join, bot)
            mock_proc.assert_called_once_with(event_join, bot)

        # Прямой вход по ссылке
        member_event = MagicMock()
        member_event.chat.id = -1001234567890
        member_event.new_chat_member.user.id = 9002

        await vip_services.cb_vip_member_joined(member_event)
        self.assertTrue(await db.is_vip_channel_member(9002))


def aiosqlite_conn():
    import aiosqlite
    return aiosqlite.connect(TEST_DB)


if __name__ == "__main__":
    unittest.main()
