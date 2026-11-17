from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import asyncio

import config
import database as db
import keyboards as kb
from services import autopilot, news, affiliate, vip_channel, vip_autopilot

router = Router()

class AdminState(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_grant = State()

def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID

@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return
        
    await state.clear()
    text = (
        f"👑 <b>Панель управления администратора</b>\n\n"
        f"Управление проектом {config.PROJECT_NAME}:\n"
        f"• Канал для автопостинга: <code>{config.CHANNEL_ID or 'Не настроен'}</code>\n"
        f"• Автопостинг: <b>новости (каждые 30 мин)</b> + <b>сводка рынка (каждые 4 ч)</b>."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_admin_panel())
    await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
        
    stats = await db.get_stats()
    text = (
        f"📊 <b>Статистика проекта {config.PROJECT_NAME}:</b>\n\n"
        f"👥 Всего пользователей в базе: <b>{stats['total_users']}</b>\n"
        f"💎 Активных VIP-подписок: <b>{stats['active_subs']}</b>\n\n"
        f"💰 <b>Выручка:</b>\n"
        f"• Telegram Stars: <b>{stats['stars_revenue']} ⭐</b>\n"
        f"• Рубли (СБП/Карты): <b>{stats['rub_revenue']} ₽</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_admin_panel())
    await callback.answer()

@router.callback_query(F.data == "admin_post_channel")
async def cb_admin_post_channel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
        
    if not config.CHANNEL_ID:
        await callback.answer("⚠️ CHANNEL_ID не указан!", show_alert=True)
        return
        
    await callback.answer("⏳ Генерируем аналитику и отправляем в канал...")
    success = await autopilot.publish_market_update(callback.bot)
    
    if success:
        await callback.message.answer(f"✅ Аналитический пост успешно опубликован в канал {config.CHANNEL_ID}!")
    else:
        await callback.message.answer(f"❌ Ошибка публикации сводки в канал.")

@router.callback_query(F.data == "admin_post_news")
async def cb_admin_post_news(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
        
    if not config.CHANNEL_ID:
        await callback.answer("⚠️ CHANNEL_ID не указан!", show_alert=True)
        return
        
    await callback.answer("⏳ Проверяем свежие новости...")
    success = await news.publish_latest_news(callback.bot)
    
    if success:
        await callback.message.answer(f"✅ Свежая новость успешно опубликована в канал {config.CHANNEL_ID}!")
    else:
        await callback.message.answer("ℹ️ Все последние новости уже были опубликованы в канале.")

@router.callback_query(F.data == "admin_post_alert")
async def cb_admin_post_alert(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
        
    if not config.CHANNEL_ID:
        await callback.answer("⚠️ CHANNEL_ID не указан!", show_alert=True)
        return
        
    await callback.answer("⏳ Сканируем рынок на предмет резких импульсов...")
    success = await autopilot.publish_flash_alert(callback.bot)
    
    if success:
        await callback.message.answer(f"✅ Flash-Алерт успешно отправлен в канал {config.CHANNEL_ID}!")
    else:
        await callback.message.answer("ℹ️ Сейчас нет экстремальных аномалий (RSI в норме, сильных пампов/дампов нет).")

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
        
    await state.set_state(AdminState.waiting_for_broadcast)
    text = (
        "📢 <b>Режим массовой рассылки</b>\n\n"
        "Отправьте следующее сообщение, которое будет разослано всем пользователям бота.\n\n"
        "<i>Для отмены отправьте /cancel</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()

@router.message(AdminState.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
        
    if message.text and message.text == "/cancel":
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=kb.get_admin_panel())
        return
        
    users = await db.get_all_users()
    await state.clear()
    
    status_msg = await message.answer(f"⏳ Запуск рассылки на {len(users)} пользователей...")
    success_count = 0
    blocked_count = 0
    
    for uid in users:
        try:
            await message.copy_to(chat_id=uid)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            blocked_count += 1
            
    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"Доставлено: <b>{success_count}</b>\n"
        f"Ошибок: <b>{blocked_count}</b>",
        parse_mode="HTML",
        reply_markup=kb.get_admin_panel()
    )

@router.callback_query(F.data == "admin_grant")
async def cb_admin_grant(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
        
    await state.set_state(AdminState.waiting_for_grant)
    text = (
        "➕ <b>Ручная выдача подписки</b>\n\n"
        "Введите <code>ID_пользователя</code> и <code>количество_дней</code> через пробел (например: <code>123456789 30</code>):"
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()

@router.message(AdminState.waiting_for_grant)
async def process_grant(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
        
    if not message.text:
        await message.answer("❌ Неверный формат. Введите ID и дни через пробел (например: <code>123456789 30</code>):", parse_mode="HTML")
        return

    if message.text == "/cancel":
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=kb.get_admin_panel())
        return
        
    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("❌ Неверный формат. Введите ID и дни через пробел (например: <code>123456789 30</code>):", parse_mode="HTML")
        return
        
    target_id = int(parts[0])
    days = int(parts[1])
    
    await db.add_subscription_days(target_id, days)
    await state.clear()
    
    # Генерация персональной ссылки в VIP-канал (с фоллбэком на VIP_LINK)
    vip_link = await vip_channel.create_vip_invite_link(message.bot, target_id)
    if not vip_link:
        vip_link = config.VIP_LINK
    await db.record_vip_channel_join(target_id)
    
    try:
        await message.bot.send_message(
            target_id,
            f"🎁 <b>Вам начислен VIP-доступ на +{days} дней!</b>\n\n"
            f"👉 Ссылка в клуб: <a href='{vip_link}'>Войти в закрытый VIP-канал</a>",
            parse_mode="HTML"
        )
    except Exception:
        pass
        
    await message.answer(
        f"✅ Пользователю <code>{target_id}</code> начислено <b>{days}</b> дней доступа.\n"
        f"🔗 Ссылка в канал: <code>{vip_link}</code>",
        parse_mode="HTML",
        reply_markup=kb.get_admin_panel()
    )

# ==================== УПРАВЛЕНИЕ ЗАКРЫТЫМ VIP-КАНАЛОМ В АДМИНКЕ ====================

@router.message(Command("vip_channel_status", "channel_status"))
@router.callback_query(F.data == "admin_vip_channel_status")
async def cb_admin_vip_channel_status(event: Message | CallbackQuery):
    """Проверка прав бота, ID канала и участников закрытого VIP-канала."""
    is_callback = isinstance(event, CallbackQuery)
    user_id = event.from_user.id
    if not is_admin(user_id):
        if is_callback:
            await event.answer("Доступ запрещен.", show_alert=True)
        return

    bot = event.bot
    status_info = await vip_channel.check_bot_channel_permissions(bot)

    if not status_info["ok"]:
        text = (
            f"🔐 <b>Статус закрытого VIP-канала:</b>\n\n"
            f"⚠️ <b>Внимание:</b> {status_info.get('error')}\n"
            f"ID канала: <code>{status_info.get('channel_id') or 'Не настроен'}</code>\n\n"
            f"<i>Для включения динамического управления укажите VIP_CHANNEL_ID в .env "
            f"и добавьте бота в канал администратором.</i>"
        )
    else:
        invite_icon = "✅" if status_info["can_invite_users"] else "❌"
        restrict_icon = "✅" if status_info["can_restrict_members"] else "❌"
        post_icon = "✅" if status_info["can_post_messages"] else "❌"
        admin_icon = "✅ Администратор" if status_info["is_admin"] else "❌ Не администратор"

        text = (
            f"🔐 <b>Статус закрытого VIP-канала {config.PROJECT_NAME}:</b>\n\n"
            f"📢 <b>Канал:</b> {status_info['title']} (<code>{status_info['channel_id']}</code>)\n"
            f"👤 <b>Статус бота:</b> {admin_icon}\n\n"
            f"🛠 <b>Права администратора бота:</b>\n"
            f"• Создание персональных ссылок (invite): {invite_icon}\n"
            f"• Исключение истекших участников (ban/kick): {restrict_icon}\n"
            f"• Публикация постов (post): {post_icon}\n\n"
            f"👥 <b>Участники:</b>\n"
            f"• В канале Telegram: <b>{status_info['tg_members_count']}</b> чел.\n"
            f"• Активных VIP-подписчиков в БД: <b>{status_info['db_members_count']}</b> чел.\n\n"
            f"⚡ <b>Режим:</b> Динамическое управление доступом (одноразовые ссылки + автокик)."
        )

    if is_callback:
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_admin_vip_channel_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb.get_admin_vip_channel_keyboard())

@router.callback_query(F.data == "admin_kick_expired")
async def cb_admin_kick_expired(callback: CallbackQuery):
    """Ручной запуск исключения пользователей с истекшей подпиской из закрытого канала."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    await callback.answer("⏳ Проверяем участников и исключаем истекшие подписки...")
    kicked = await vip_channel.check_and_kick_expired_members(callback.bot)

    if kicked > 0:
        await callback.message.answer(
            f"✅ <b>Очистка завершена!</b>\nИсключено участников с истекшей подпиской: <b>{kicked}</b>",
            parse_mode="HTML",
            reply_markup=kb.get_admin_vip_channel_keyboard()
        )
    else:
        await callback.message.answer(
            "ℹ️ <b>Нет участников с истекшей подпиской.</b> Все подписчики в канале активны!",
            parse_mode="HTML",
            reply_markup=kb.get_admin_vip_channel_keyboard()
        )

# ==================== ТЕСТОВЫЕ ПУБЛИКАЦИИ В ЗАКРЫТЫЙ VIP-КАНАЛ ====================

@router.callback_query(F.data == "admin_test_vip_setup")
async def cb_admin_test_vip_setup(callback: CallbackQuery):
    """Ручной триггер: публикация VIP торгового сигнала в закрытый канал."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    if not config.VIP_CHANNEL_ID:
        await callback.answer("⚠️ VIP_CHANNEL_ID не указан!", show_alert=True)
        return

    await callback.answer("⏳ Анализируем рынок и генерируем VIP торговый сетап...")
    success = await vip_autopilot.publish_vip_trade_setup(callback.bot)

    if success:
        await callback.message.answer(
            f"✅ <b>VIP Trade Setup успешно опубликован в канал <code>{config.VIP_CHANNEL_ID}</code>!</b>",
            parse_mode="HTML",
            reply_markup=kb.get_admin_panel()
        )
    else:
        await callback.message.answer(
            "❌ <b>Ошибка публикации VIP торгового сетапа.</b> Проверьте права бота в канале.",
            parse_mode="HTML",
            reply_markup=kb.get_admin_panel()
        )

@router.callback_query(F.data == "admin_test_vip_morning")
async def cb_admin_test_vip_morning(callback: CallbackQuery):
    """Ручной триггер: публикация VIP утреннего брифинга в закрытый канал."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    if not config.VIP_CHANNEL_ID:
        await callback.answer("⚠️ VIP_CHANNEL_ID не указан!", show_alert=True)
        return

    await callback.answer("⏳ Формируем утренний брифинг и роадмап...")
    success = await vip_autopilot.publish_vip_morning_briefing(callback.bot)

    if success:
        await callback.message.answer(
            f"✅ <b>VIP Morning Briefing успешно опубликован в канал <code>{config.VIP_CHANNEL_ID}</code>!</b>",
            parse_mode="HTML",
            reply_markup=kb.get_admin_panel()
        )
    else:
        await callback.message.answer(
            "❌ <b>Ошибка публикации VIP брифинга.</b> Проверьте права бота в канале.",
            parse_mode="HTML",
            reply_markup=kb.get_admin_panel()
        )

@router.callback_query(F.data == "admin_test_vip_whale")
async def cb_admin_test_vip_whale(callback: CallbackQuery):
    """Ручной триггер: публикация Whale алерта в закрытый канал."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен.", show_alert=True)
        return

    if not config.VIP_CHANNEL_ID:
        await callback.answer("⚠️ VIP_CHANNEL_ID не указан!", show_alert=True)
        return

    await callback.answer("⏳ Сканируем orderflow и аномалии объемов...")
    success = await vip_autopilot.publish_vip_whale_alert(callback.bot, force=True)

    if success:
        await callback.message.answer(
            f"✅ <b>Whale Orderflow Alert успешно опубликован в канал <code>{config.VIP_CHANNEL_ID}</code>!</b>",
            parse_mode="HTML",
            reply_markup=kb.get_admin_panel()
        )
    else:
        await callback.message.answer(
            "❌ <b>Ошибка отправки Whale алерта.</b> Проверьте права бота в канале.",
            parse_mode="HTML",
            reply_markup=kb.get_admin_panel()
        )

# ==================== B2B ПАРТНЕРЫ И ВЫПЛАТЫ В АДМИНКЕ ====================

@router.callback_query(F.data == "admin_partners")
async def cb_admin_partners(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
        
    summary = await db.get_admin_partners_summary()
    has_pending = summary["pending_count"] > 0
    
    text = (
        f"🤝 <b>B2B Партнерская программа & Выплаты:</b>\n\n"
        f"👥 Зарегистрировано партнеров: <b>{summary['total_partners']}</b>\n\n"
        f"💰 <b>Начисленные партнерские вознаграждения (30% Rev-Share):</b>\n"
        f"• Telegram Stars: <b>{summary['affiliate_stars']} ⭐</b>\n"
        f"• Рубли (СБП): <b>{summary['affiliate_rub']} ₽</b>\n\n"
        f"⏳ <b>Ожидают выплаты:</b>\n"
        f"• Заявок в очереди: <b>{summary['pending_count']}</b> шт.\n"
        f"• К выплате Stars: <b>{summary['pending_stars']} ⭐</b>\n"
        f"• К выплате RUB: <b>{summary['pending_rub']} ₽</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_admin_partners_keyboard(has_pending))
    await callback.answer()

@router.callback_query(F.data == "admin_payouts_list")
async def cb_admin_payouts_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
        
    pending = await db.get_pending_payout_requests()
    if not pending:
        await callback.message.edit_text(
            "ℹ️ <b>Очередь выплат пуста!</b>\nВсе заявки обработаны.",
            parse_mode="HTML",
            reply_markup=kb.get_admin_partners_keyboard(False)
        )
        await callback.answer()
        return
        
    await callback.message.edit_text(
        f"📋 <b>Список заявок на партнерский вывод ({len(pending)}):</b>",
        parse_mode="HTML"
    )
    
    for p in pending:
        unit = "⭐" if p["currency"] == "XTR" else "₽"
        uname = f"@{p['username']}" if p.get("username") else f"ID {p['partner_id']}"
        slug = p.get("partner_code") or "N/A"
        
        card_text = (
            f"💸 <b>Заявка #{p['id']}</b>\n"
            f"Партнер: {uname} (Код: <code>{slug}</code>)\n"
            f"Сумма: <b>{p['amount']} {unit}</b> ({p['currency']})\n"
            f"Реквизиты: <code>{p['details']}</code>\n"
            f"Дата: <i>{p['created_at'][:16].replace('T', ' ')}</i>"
        )
        await callback.message.answer(
            card_text,
            parse_mode="HTML",
            reply_markup=kb.get_admin_payout_approval_keyboard(p["id"])
        )
        
    await callback.answer()

@router.callback_query(F.data.startswith("adm_pay_app_"))
async def cb_admin_payout_approve(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
        
    payout_id = int(callback.data.replace("adm_pay_app_", ""))
    ok, msg, payout = await affiliate.approve_payout(payout_id)
    
    if not ok:
        await callback.answer(msg, show_alert=True)
        return
        
    unit = "⭐" if payout["currency"] == "XTR" else "₽"
    # Уведомляем партнера
    try:
        partner_msg = (
            f"✅ <b>Ваша выплата #{payout_id} подтверждена!</b>\n\n"
            f"Сумма <b>{payout['amount']} {unit}</b> переведена по вашим реквизитам:\n"
            f"<code>{payout['details']}</code>\n\n"
            f"Спасибо за плодотворное сотрудничество!"
        )
        await callback.bot.send_message(payout["partner_id"], partner_msg, parse_mode="HTML")
    except Exception:
        pass
        
    try:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n✅ <b>ВЫПЛАЧЕНО администратором</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass
        
    await callback.answer("Выплата успешно подтверждена!")

@router.callback_query(F.data.startswith("adm_pay_rej_"))
async def cb_admin_payout_reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
        
    payout_id = int(callback.data.replace("adm_pay_rej_", ""))
    ok, msg, payout = await affiliate.reject_payout(payout_id, "Отклонено администратором")
    
    if not ok:
        await callback.answer(msg, show_alert=True)
        return
        
    unit = "⭐" if payout["currency"] == "XTR" else "₽"
    # Уведомляем партнера о возврате
    try:
        partner_msg = (
            f"⚠️ <b>Заявка на выплату #{payout_id} отклонена.</b>\n\n"
            f"Средства в размере <b>{payout['amount']} {unit}</b> возвращены на ваш партнерский баланс.\n"
            f"Пожалуйста, проверьте корректность реквизитов и повторите запрос."
        )
        await callback.bot.send_message(payout["partner_id"], partner_msg, parse_mode="HTML")
    except Exception:
        pass
        
    try:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n❌ <b>ОТКЛОНЕНО (средства возвращены на баланс партнера)</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass
        
    await callback.answer("Заявка отклонена, баланс возвращен партнеру.")

