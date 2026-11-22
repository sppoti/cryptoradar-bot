from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import datetime
import os

import config
import database as db
import keyboards as kb
from services import affiliate, traffic_funnel, vip_channel, ai_analytics
from handlers import vip_services
from handlers.payments import ManualPaymentState

router = Router()

class PartnerState(StatesGroup):
    waiting_for_slug = State()
    waiting_for_payout_amount = State()
    waiting_for_payout_details = State()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or "Трейдер"
    
    # Обработка deep links: /start pay_sub_1m, /start receipt, /start ref_123456
    referrer_id = None
    msg_text = message.text or message.caption or ""
    args = msg_text.split()
    if len(args) > 1:
        param = args[1]
        
        # Deep link: Оплата Stars через WebApp
        if param.startswith("pay_"):
            tariff_key = param.replace("pay_stars_", "").replace("pay_", "")
            tariff = config.TARIFFS.get(tariff_key)
            if tariff:
                await db.get_or_create_user(user_id, username, first_name)
                await message.bot.send_invoice(
                    chat_id=user_id,
                    title=f"Оплата: {tariff['title']}",
                    description=f"{tariff['description']}\n⚡ Автоматическая выдача: подписка активируется мгновенно сразу после оплаты Telegram Stars.",
                    payload=f"stars_{tariff_key}_{user_id}",
                    currency="XTR",  # Telegram Stars
                    prices=[LabeledPrice(label=tariff['title'], amount=tariff['stars'])],
                    provider_token=""
                )
                return
        
        # Deep link: Отправка чека СБП из WebApp
        elif param in ("receipt", "manual_pay", "sbp"):
            await db.get_or_create_user(user_id, username, first_name)
            await state.set_state(ManualPaymentState.waiting_for_receipt)
            await state.update_data(tariff_key="sub_3m")
            text = (
                f"💳 <b>Оплата подписки по СБП / Карте</b>\n\n"
                f"{config.MANUAL_PAYMENT_DETAILS}\n\n"
                f"📌 <b>ИНСТРУКЦИЯ:</b>\n"
                f"1. Переведите сумму выбранного тарифа (150 ₽ / 1200 ₽ / 3500 ₽) по реквизитам выше.\n"
                f"2. <b>Отправьте ответным сообщением чек, фото или скриншот перевода.</b>\n\n"
                f"<i>После отправки чека администратор подтвердит доступ!</i>"
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb.get_back_to_menu())
            return
            
        # Deep link: Тарифы
        elif param in ("tariffs", "vip"):
            await db.get_or_create_user(user_id, username, first_name)
            text = (
                f"💎 <b>Тарифные планы {config.PROJECT_NAME}</b>\n\n"
                f"Выберите подходящий период подписки:\n"
                f"• Доступ ко всем Flash-сигналам и целям\n"
                f"• Живой радар перекупленности/перепроданности\n"
                f"• Закрытый VIP-канал и база знаний"
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb.get_tariffs_keyboard())
            return

        # Deep link: Поддержка
        elif param == "support":
            await db.get_or_create_user(user_id, username, first_name)
            admin_contact = f"tg://user?id={config.ADMIN_ID}" if config.ADMIN_ID else "@admin"
            text = (
                f"💬 <b>Служба заботы и поддержки {config.PROJECT_NAME}</b>\n\n"
                f"По любым вопросам доступа, оплат или предложений напишите администратору:\n"
                f"👤 Контакт: {admin_contact}\n\n"
                f"Либо отправьте ваш вопрос или чек ответным сообщением сюда."
            )
            await message.answer(text, parse_mode="HTML", reply_markup=kb.get_back_to_menu())
            return

        # Deep link: Запуск WebApp терминала
        elif param.startswith("terminal"):
            await db.get_or_create_user(user_id, username, first_name)
            user_id = message.from_user.id
            is_vip = (user_id == config.ADMIN_ID) or await db.is_sub_active(user_id)
            coin = (param.replace("terminal_", "") if param.startswith("terminal_") else "BTC").upper()
            if not coin or coin == "TERMINAL":
                coin = "BTC"
            base_webapp = config.WEBAPP_URL or ""
            sep = "&" if "?" in base_webapp else "?"
            api_url = os.getenv("RENDER_EXTERNAL_URL", "https://cryptoradar-bot-z1r3.onrender.com")
            tma_url = f"{base_webapp}{sep}user_id={user_id}&vip={'1' if is_vip else '0'}&symbol={coin}&api={api_url}"
            status_text = "💎 <b>PRO VIP Активен</b>" if is_vip else "🔒 <b>Базовый доступ (Free)</b>"
            text = (
                "🚀 <b>Торговый терминал CryptoRadar PRO</b>\n\n"
                f"📌 Актив: <b>{coin}/USDT</b>\n"
                f"Статус: {status_text}\n\n"
                "Нажмите кнопку ниже, чтобы запустить интерактивный терминал с живыми графиками прямо внутри Telegram:"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"📊 Запустить терминал ({coin})", web_app=WebAppInfo(url=tma_url))],
                [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
            ])
            await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
            return

        # Deep link: Экспресс-анализ монеты
        elif param.startswith("analyze_") or param == "analyze":
            await db.get_or_create_user(user_id, username, first_name)
            user_id = message.from_user.id
            is_vip = (user_id == config.ADMIN_ID) or await db.is_sub_active(user_id)
            coin = (param.replace("analyze_", "") if param.startswith("analyze_") else "BTC").upper()
            if not coin or coin == "ANALYZE":
                coin = "BTC"
            if is_vip:
                report = await ai_analytics.format_analysis_report(coin)
                await message.answer(report, parse_mode="HTML", reply_markup=kb.get_analysis_result_keyboard(coin))
            else:
                await message.answer(
                    vip_services.get_vip_teaser_text(),
                    parse_mode="HTML",
                    reply_markup=kb.get_vip_teaser_keyboard()
                )
            return

        # Реферальный код
        else:
            resolved_ref = await db.resolve_referrer_code(param)
            if resolved_ref and resolved_ref != user_id:
                referrer_id = resolved_ref

    await db.get_or_create_user(user_id, username, first_name, referrer_id)
    is_admin = (user_id == config.ADMIN_ID)
    is_vip = await db.is_sub_active(user_id)
    
    text = (
        f"<b>┌── [ TERMINAL 2.0 // CRYPTORADAR PRO ]</b>\n"
        f"│ 👋 Приветствуем в SaaS-платформе мониторинга крипторынка и закрытой аналитики.\n"
        f"├── <b>ДОСТУПНЫЙ ФУНКЦИОНАЛ:</b>\n"
        f"│ • <b>⚡ WebApp Терминал (PRO):</b> TradingView, живой RSI-сканер, AI-сетапы\n"
        f"│ • <b>📊 Экспресс-анализ (VIP):</b> расчет индикаторов RSI (1h/4h) и вердикт\n"
        f"│ • <b>🧠 Deep AI-прогноз:</b> квантовые торговые планы и уровни TP/SL\n"
        f"│ • <b>🚨 Радар сигналов (RSI):</b> зоны экстремальной перекупленности\n"
        f"│ • <b>🖼 Сетап-карта (PNG):</b> графические карточки для шеринга\n"
        f"│ • <b>💎 VIP-клуб & Канал:</b> закрытые инсайды и автопилот-сигналы\n"
        f"│ • <b>🤝 Партнерам (30% RevShare):</b> пожизненный пассивный доход\n"
        f"<b>└── [ ВЫБЕРИТЕ РАЗДЕЛ В МЕНЮ НИЖЕ ]</b>"
    )
    
    await message.answer(text, parse_mode="HTML", reply_markup=kb.get_main_menu(is_admin, user_id=user_id, is_vip=is_vip))

@router.message(Command("webapp"))
@router.message(Command("app"))
async def cmd_webapp(message: Message):
    """Команда /webapp или /app для открытия Mini App терминала."""
    user_id = message.from_user.id
    is_vip = await db.is_sub_active(user_id)
    text = (
        f"<b>┌── [ TERMINAL 2.0 // WEBAPP TERMINAL PRO ]</b>\n"
        f"│ Институциональный торговый терминал прямо внутри Telegram:\n"
        f"├── <b>ВОЗМОЖНОСТИ ТЕРМИНАЛА:</b>\n"
        f"│ • <b>Живой график TradingView</b> с поддержкой RSI и EMA\n"
        f"│ • <b>Радар аномалий</b> и зон перекупленности/перепроданности\n"
        f"│ • <b>AI-сигналы</b> со скорингом точности, целями TP1/TP2 и Stop-Loss\n"
        f"│ • <b>Мгновенное управление VIP</b> через Telegram Stars (⭐)\n"
        f"<b>└── [ НАЖМИТЕ КНОПКУ НИЖЕ ДЛЯ ЗАПУСКА ]</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb.get_webapp_keyboard(user_id=user_id, is_vip=is_vip))

@router.message(Command("help", "menu"))
async def cmd_help(message: Message):
    """Команда /help или /menu для быстрой навигации."""
    user_id = message.from_user.id
    is_admin = (user_id == config.ADMIN_ID)
    is_vip = await db.is_sub_active(user_id)
    text = (
        f"<b>┌── [ TERMINAL 2.0 // НАВИГАЦИЯ И КОМАНДЫ ]</b>\n"
        f"│ • <b>/start</b> — Главное меню платформы\n"
        f"│ • <b>/webapp</b> или <b>/app</b> — Запуск Mini App терминала\n"
        f"│ • <b>/forecast &lt;тикер&gt;</b> или <b>/ai &lt;тикер&gt;</b> — Глубокий AI-прогноз\n"
        f"│ • <b>/partner</b> или <b>/affiliate</b> — Кабинет партнера (30% RevShare)\n"
        f"│ • <b>/leaderboard</b> или <b>/top</b> — Турнир рефералов\n"
        f"│ • <b>/help</b>, <b>/menu</b> — Справка по командам\n"
        f"<b>└── [ ВЫБЕРИТЕ РАЗДЕЛ В МЕНЮ НИЖЕ ]</b>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb.get_main_menu(is_admin, user_id=user_id, is_vip=is_vip))

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    is_admin = (user_id == config.ADMIN_ID)
    is_vip = await db.is_sub_active(user_id)
    text = (
        f"<b>┌── [ TERMINAL 2.0 // ГЛАВНОЕ МЕНЮ ]</b>\n"
        f"│ Выберите интересующий раздел платформы:\n"
        f"<b>└── [ {config.PROJECT_NAME} ]</b>"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_main_menu(is_admin, user_id=user_id, is_vip=is_vip))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb.get_main_menu(is_admin, user_id=user_id, is_vip=is_vip))
    await callback.answer()

@router.callback_query(F.data == "tariffs")
async def cb_tariffs(callback: CallbackQuery):
    text = (
        f"💎 <b>Тарифные планы {config.PROJECT_NAME}:</b>\n\n"
        f"Выберите подходящий период подписки:\n\n"
    )
    for key, data in config.TARIFFS.items():
        text += f"🔹 <b>{data['title']}</b> — <b>{data['stars']} ⭐</b>\n"
        text += f"   <i>{data['description']}</i>\n\n"
    text += "⚡ <b>Автоматическая выдача:</b> подписка активируется мгновенно сразу после оплаты Telegram Stars."
        
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_tariffs_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("tariff_"))
async def cb_tariff_detail(callback: CallbackQuery):
    tariff_key = callback.data.replace("tariff_", "")
    tariff = config.TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
        
    text = (
        f"💎 <b>Выбран тариф: {tariff['title']}</b>\n\n"
        f"⏱ <b>Срок действия:</b> {tariff['days']} дней\n"
        f"📝 <b>Описание:</b> {tariff['description']}\n\n"
        f"💰 <b>Стоимость:</b> <b>{tariff['stars']} ⭐</b>\n\n"
        f"⚡ <b>Автоматическая выдача:</b> подписка активируется мгновенно сразу после оплаты Telegram Stars."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_payment_methods(tariff_key))
    await callback.answer()

@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    is_active = (user_id == config.ADMIN_ID) or await db.is_sub_active(user_id)
    ref_count = await db.get_referral_count(user_id)
    
    sub_status = "❌ <b>Не активна</b>"
    if is_active and user and user["sub_until"]:
        try:
            dt = datetime.datetime.fromisoformat(user["sub_until"])
            sub_status = f"✅ <b>Активна до:</b> {dt.strftime('%d.%m.%Y %H:%M')}"
        except Exception:
            sub_status = "✅ <b>Активна</b>"
    elif is_active:
        sub_status = "✅ <b>Активна (Администратор)</b>"
            
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    text = (
        f"👤 <b>Ваш профиль:</b>\n\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"Статус VIP: {sub_status}\n\n"
        f"👥 <b>Приглашено рефералов:</b> {ref_count}\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>\n\n"
    )
    
    if is_active:
        text += (
            f"🎉 <b>Статус: VIP-участник</b>\n"
            f"Нажмите кнопку <b>«🔐 Перейти в VIP-канал»</b> ниже, чтобы получить персональную ссылку и войти в закрытый канал.\n\n"
        )
    else:
        text += "💡 Оформите подписку в разделе «💎 Оформить VIP», чтобы разблокировать сигналы и закрытый канал.\n\n"
        
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_profile_keyboard(is_active), disable_web_page_preview=True)
    await callback.answer()

@router.message(Command("vip", "vip_channel", "join_vip"))
@router.callback_query(F.data == "enter_vip_channel")
async def cb_enter_vip_channel(event: Message | CallbackQuery):
    """Генерация свежей персональной ссылки для входа в закрытый VIP-канал."""
    is_callback = isinstance(event, CallbackQuery)
    user_id = event.from_user.id
    bot = event.bot

    is_active = (user_id == config.ADMIN_ID) or await db.is_sub_active(user_id)
    if not is_active:
        teaser = (
            "🔒 <b>Доступ в закрытый VIP-канал ограничен</b>\n\n"
            "У вас нет активной VIP-подписки. Оформите тариф в меню ниже, "
            "чтобы получить персональную ссылку и доступ к инсайдерским сигналам:"
        )
        if is_callback:
            await event.message.edit_text(teaser, parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
            await event.answer()
        else:
            await event.answer(teaser, parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        return

    vip_link = await vip_channel.create_vip_invite_link(bot, user_id)
    if not vip_link:
        vip_link = config.VIP_LINK
    await db.record_vip_channel_join(user_id)

    text = (
        f"💎 <b>Вход в закрытый VIP Club {config.PROJECT_NAME}</b>\n\n"
        f"✅ Ваша подписка активна!\n"
        f"🔑 <b>Персональная ссылка для входа:</b>\n"
        f"<code>{vip_link}</code>\n\n"
        f"<i>Ссылка одноразовая и действует 24 часа. Не передавайте её третьим лицам.</i>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Перейти в закрытый VIP-канал", url=vip_link)],
        [
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"),
            InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")
        ]
    ])
    if is_callback:
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=markup)

@router.callback_query(F.data == "referrals")
async def cb_referrals(callback: CallbackQuery):
    user_id = callback.from_user.id
    ref_count = await db.get_referral_count(user_id)
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    text = (
        f"🎁 <b>Партнерская программа</b>\n\n"
        f"Приглашайте друзей и пользуйтесь всеми VIP-инструментами бесплатно!\n\n"
        f"🌟 За каждого друга, перешедшего по вашей ссылке и запустившего бота, вы получаете <b>+3 дня VIP-подписки бесплатно</b>!\n\n"
        f"📊 Вы уже пригласили: <b>{ref_count}</b> чел.\n\n"
        f"Ваша персональная ссылка для приглашений:\n"
        f"<code>{ref_link}</code>\n\n"
        f"<i>(Нажмите на ссылку, чтобы скопировать её)</i>"
    )
    markup = kb.InlineKeyboardMarkup(inline_keyboard=[
        [kb.InlineKeyboardButton(text="🏆 Турнир рефералов (Топ лидеров)", callback_data="leaderboard")],
        [kb.InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    await callback.answer()

@router.message(Command("leaderboard"))
@router.message(Command("top"))
@router.callback_query(F.data == "leaderboard")
async def cb_leaderboard(event: Message | CallbackQuery):
    is_callback = isinstance(event, CallbackQuery)
    user_id = event.from_user.id
    message = event.message if is_callback else event
    
    top_users = await db.get_top_referrers(10)
    user_rank, user_refs = await db.get_user_rank(user_id)
    
    lines = [
        "🏆 <b>ЕЖЕНЕДЕЛЬНЫЙ ТУРНИР РЕФЕРАЛОВ</b>",
        "────────────────────",
        "Приглашайте друзей по своей ссылке и выигрывайте ценные призы!",
        "",
        "🎁 <b>Призы каждую неделю:</b>",
        "🥇 <b>1 место:</b> 3 месяца VIP-доступа",
        "🥈 <b>2 место:</b> 1 месяц VIP-доступа",
        "🥉 <b>3 место:</b> 2 недели VIP-доступа",
        "🎖 <b>4–10 места:</b> +5 дней VIP к подписке",
        "",
        "📊 <b>ТОП-10 лидеров прямо сейчас:</b>"
    ]
    
    if not top_users:
        lines.append("<i>Пока в таблице никого нет — станьте первым и займите 1-е место!</i>")
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for idx, u in enumerate(top_users):
            m = medals[idx] if idx < len(medals) else f"{idx+1}."
            raw_name = u["display_name"] or "Участник"
            clean_name = f"@{raw_name[:3]}***" if not raw_name.startswith("@") else f"{raw_name[:4]}***"
            lines.append(f"{m} <b>{clean_name}</b> — <b>{u['ref_count']}</b> приглашенных")
            
    bot_info = await event.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    
    rank_str = f"#{user_rank}" if user_rank > 0 else "Вне рейтинга (0 рефералов)"
    lines.extend([
        "",
        "────────────────────",
        "👤 <b>Ваша статистика:</b>",
        f"• Ваше место: <b>{rank_str}</b>",
        f"• Приглашено друзей: <b>{user_refs} чел.</b>",
        "",
        "🔗 <b>Ваша ссылка для участия:</b>",
        f"<code>{ref_link}</code>",
        "",
        "⏳ <i>Итоги турнира подводятся автоматически каждое воскресенье!</i>"
    ])
    
    full_text = "\n".join(lines)
    if is_callback:
        await message.edit_text(full_text, parse_mode="HTML", reply_markup=kb.get_leaderboard_keyboard())
        await event.answer()
    else:
        await message.answer(full_text, parse_mode="HTML", reply_markup=kb.get_leaderboard_keyboard())

@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    admin_contact = f"tg://user?id={config.ADMIN_ID}" if config.ADMIN_ID else "@admin"
    text = (
        f"💬 <b>Служба поддержки и вопросы</b>\n\n"
        f"Если у вас возникли сложности с оплатой или вопросы по сигналам, напишите нам:\n\n"
        f"👉 Администратор: {admin_contact}\n\n"
        f"Мы отвечаем ежедневно с 10:00 до 22:00."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_back_to_menu())
    await callback.answer()

# ==================== B2B ПАРТНЕРСКИЙ КАБИНЕТ И ХЕНДЛЕРЫ ====================

@router.message(Command("partner"))
@router.message(Command("affiliate"))
@router.callback_query(F.data == "partner_dashboard")
async def cb_partner_dashboard(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = event.from_user.id
    bot_info = await event.bot.get_me()
    
    dashboard_data = await affiliate.get_partner_dashboard(user_id, bot_info.username)
    text = affiliate.format_dashboard_text(dashboard_data)
    reply_markup = kb.get_partner_dashboard_keyboard()
    
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception:
            await event.message.answer(text, parse_mode="HTML", reply_markup=reply_markup, disable_web_page_preview=True)
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=reply_markup, disable_web_page_preview=True)

@router.callback_query(F.data == "partner_set_slug")
async def cb_partner_set_slug(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PartnerState.waiting_for_slug)
    bot_info = await callback.bot.get_me()
    text = (
        "🏷 <b>Настройка индивидуального реферального кода (slug)</b>\n\n"
        "Задайте запоминающийся код для вашего канала или блога (например: <code>cryptoclub</code>, <code>whale_trade</code>).\n\n"
        f"Ваша ссылка будет иметь вид:\n"
        f"<code>https://t.me/{bot_info.username}?start=ref_ваш_код</code>\n\n"
        "📌 <i>Требования: от 3 до 32 символов (буквы, цифры, знак _). Не может состоять только из цифр.</i>\n\n"
        "Отправьте желаемый код сообщением или введите /cancel для отмены:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_back_to_partner())
    await callback.answer()

@router.message(PartnerState.waiting_for_slug)
async def process_partner_slug(message: Message, state: FSMContext):
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Настройка реф-кода отменена.", reply_markup=kb.get_back_to_partner())
        return
        
    user_id = message.from_user.id
    new_slug = (message.text or "").strip()
    
    ok, msg = await affiliate.set_custom_slug(user_id, new_slug)
    if not ok:
        await message.answer(f"❌ <b>Ошибка:</b> {msg}\n\nПопробуйте другой код или отправьте /cancel:", parse_mode="HTML")
        return
        
    await state.clear()
    bot_info = await message.bot.get_me()
    custom_link = f"https://t.me/{bot_info.username}?start=ref_{msg}"
    
    text = (
        f"✅ <b>Индивидуальный реф-код успешно сохранен:</b> <code>{msg}</code>\n\n"
        f"🔗 <b>Ваша обновленная ссылка для трафика:</b>\n"
        f"<code>{custom_link}</code>\n\n"
        f"Все переходы и оплаты подписчиков будут мгновенно учитываться в вашем дашборде с начислением 30% rev-share."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb.get_back_to_partner())

@router.callback_query(F.data == "partner_payout_select")
async def cb_partner_payout_select(callback: CallbackQuery):
    user_id = callback.from_user.id
    partner = await db.get_partner(user_id)
    balance_stars = partner.get("balance_stars", 0) if partner else 0
    balance_rub = partner.get("balance_rub", 0) if partner else 0
    
    text = (
        "💸 <b>Запрос на вывод партнерского вознаграждения</b>\n\n"
        f"💰 <b>Доступно к выводу:</b>\n"
        f"• Telegram Stars: <b>{balance_stars} ⭐</b> <i>(мин. {affiliate.MIN_PAYOUT_STARS} ⭐)</i>\n"
        f"• Рубли (СБП/Карта): <b>{balance_rub} ₽</b> <i>(мин. {affiliate.MIN_PAYOUT_RUB} ₽)</i>\n\n"
        "Выберите валюту, которую хотите вывести:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_partner_payout_currency_keyboard())
    await callback.answer()

@router.callback_query(F.data.in_({"payout_curr_XTR", "payout_curr_RUB"}))
async def cb_partner_payout_currency(callback: CallbackQuery, state: FSMContext):
    currency = "XTR" if callback.data == "payout_curr_XTR" else "RUB"
    user_id = callback.from_user.id
    partner = await db.get_partner(user_id)
    
    balance_key = "balance_stars" if currency == "XTR" else "balance_rub"
    curr_balance = partner.get(balance_key, 0) if partner else 0
    min_amount = affiliate.MIN_PAYOUT_STARS if currency == "XTR" else affiliate.MIN_PAYOUT_RUB
    unit = "⭐" if currency == "XTR" else "₽"
    
    if curr_balance < min_amount:
        await callback.answer(f"Недостаточно средств. Минимум для вывода: {min_amount} {unit}", show_alert=True)
        return
        
    await state.set_state(PartnerState.waiting_for_payout_amount)
    await state.update_data(currency=currency, max_amount=curr_balance)
    
    text = (
        f"💰 <b>Вывод {unit} ({currency})</b>\n\n"
        f"Доступно: <b>{curr_balance} {unit}</b>\n"
        f"Минимум: <b>{min_amount} {unit}</b>\n\n"
        f"Введите сумму, которую хотите вывести (числом) или /cancel для отмены:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_back_to_partner())
    await callback.answer()

@router.message(PartnerState.waiting_for_payout_amount)
async def process_payout_amount(message: Message, state: FSMContext):
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Заявка на вывод отменена.", reply_markup=kb.get_back_to_partner())
        return
        
    data = await state.get_data()
    currency = data.get("currency", "RUB")
    max_amount = data.get("max_amount", 0)
    min_amount = affiliate.MIN_PAYOUT_STARS if currency == "XTR" else affiliate.MIN_PAYOUT_RUB
    unit = "⭐" if currency == "XTR" else "₽"
    
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(f"❌ Введите целое число (например, {min_amount}):")
        return
        
    amount = int(text)
    if amount < min_amount:
        await message.answer(f"❌ Сумма меньше минимальной ({min_amount} {unit}). Введите сумму еще раз:")
        return
        
    if amount > max_amount:
        await message.answer(f"❌ Сумма превышает доступный баланс ({max_amount} {unit}). Введите сумму еще раз:")
        return
        
    await state.update_data(payout_amount=amount)
    await state.set_state(PartnerState.waiting_for_payout_details)
    
    prompt = (
        f"📋 <b>Укажите реквизиты для выплаты {amount} {unit}:</b>\n\n"
        f"• Для рублей: <code>Номер карты или Номер телефона (СБП) + название банка</code>\n"
        f"• Для Stars: <code>Ваш никнейм или TON кошелек</code>\n\n"
        f"Отправьте реквизиты сообщением или /cancel для отмены:"
    )
    await message.answer(prompt, parse_mode="HTML")

@router.message(PartnerState.waiting_for_payout_details)
async def process_payout_details(message: Message, state: FSMContext):
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Заявка на вывод отменена.", reply_markup=kb.get_back_to_partner())
        return
        
    details = (message.text or "").strip()
    if len(details) < 5:
        await message.answer("❌ Реквизиты слишком короткие. Укажите подробные реквизиты (банк, номер или адрес кошелька):")
        return
        
    data = await state.get_data()
    currency = data.get("currency", "RUB")
    amount = data.get("payout_amount", 0)
    user_id = message.from_user.id
    
    ok, msg, payout_id = await affiliate.request_payout(user_id, amount, currency, details)
    await state.clear()
    
    if not ok:
        await message.answer(f"❌ <b>Ошибка оформления заявки:</b> {msg}", parse_mode="HTML", reply_markup=kb.get_back_to_partner())
        return
        
    unit = "⭐" if currency == "XTR" else "₽"
    success_msg = (
        f"🎉 <b>Заявка на выплату #{payout_id} успешно принята!</b>\n\n"
        f"Сумма: <b>{amount} {unit}</b>\n"
        f"Реквизиты: <code>{details}</code>\n"
        f"Статус: <b>В обработке администратором</b>\n\n"
        f"Обычно выплаты переводятся в течение 24 часов. Вы получите автоматическое уведомление при завершении перевода."
    )
    await message.answer(success_msg, parse_mode="HTML", reply_markup=kb.get_back_to_partner())
    
    # Уведомляем администратора о новой заявке
    if config.ADMIN_ID:
        try:
            partner = await db.get_partner(user_id) or {}
            admin_text = affiliate.format_payout_admin_alert(
                {"id": payout_id, "partner_id": user_id, "amount": amount, "currency": currency, "details": details},
                partner
            )
            await message.bot.send_message(
                config.ADMIN_ID,
                admin_text,
                parse_mode="HTML",
                reply_markup=kb.get_admin_payout_approval_keyboard(payout_id)
            )
        except Exception as e:
            print(f"Ошибка уведомления админа о выплате: {e}")

@router.callback_query(F.data == "partner_promo_posts")
async def cb_partner_promo_posts(callback: CallbackQuery):
    user_id = callback.from_user.id
    bot_info = await callback.bot.get_me()
    dashboard = await affiliate.get_partner_dashboard(user_id, bot_info.username)
    ref_link = dashboard.get("custom_link") or dashboard.get("standard_link")
    
    posts = traffic_funnel.get_partner_channel_posts(ref_link, config.PROJECT_NAME)
    
    intro = (
        "📢 <b>Готовые промо-посты для Telegram-каналов</b>\n\n"
        "Мы подготовили рекламные креативы с высокой конверсией. "
        "В каждый пост уже вшита ваша персональная ссылка с 30% rev-share.\n"
        "Просто скопируйте нужный пост и опубликуйте в своем канале или чате 👇\n"
        "────────────────────"
    )
    await callback.message.answer(intro, parse_mode="HTML")
    
    for p in posts[:2]:
        msg_text = f"<b>[{p['category']}]</b>\n\n{p['text']}"
        await callback.message.answer(msg_text, parse_mode="HTML", disable_web_page_preview=True)
        
    await callback.message.answer(
        "💡 <i>Совет: публикуйте посты в часы пиковой активности (11:00-13:00 и 18:00-21:00 МСК) для максимального охвата.</i>",
        parse_mode="HTML",
        reply_markup=kb.get_back_to_partner()
    )
    await callback.answer()

@router.callback_query(F.data == "partner_promo_reels")
async def cb_partner_promo_reels(callback: CallbackQuery):
    user_id = callback.from_user.id
    bot_info = await callback.bot.get_me()
    partner = await db.get_partner(user_id) or {}
    slug = partner.get("partner_code", "")
    
    scripts = traffic_funnel.get_viral_video_scripts(bot_info.username, slug)
    
    intro = (
        "🎬 <b>Вирусные сценарии для TikTok, Reels и Shorts</b>\n\n"
        "Эти 30-секундные сценарии построены по формуле удержания внимания (Hook → Pain → Product Demo → CTA). "
        "Они набирают от 5,000 до 100,000+ органических просмотров без затрат на рекламу.\n"
        "────────────────────"
    )
    await callback.message.answer(intro, parse_mode="HTML")
    
    for s in scripts:
        script_text = (
            f"<b>{s['title']}</b>\n"
            f"⏱ Формат: {s['target_format']} ({s['estimated_duration']})\n\n"
            f"🪝 <b>ХУК ({s['hook']['timing']}):</b>\n"
            f"• <i>Визуал:</i> {s['hook']['visual']}\n"
            f"• <i>Озвучка:</i> «{s['hook']['voiceover']}»\n\n"
            f"📱 <b>СУТЬ ({s['body']['timing']}):</b>\n"
            f"• <i>Визуал:</i> {s['body']['visual']}\n"
            f"• <i>Озвучка:</i> «{s['body']['voiceover']}»\n\n"
            f"⚡️ <b>РАЗВЯЗКА ({s['climax']['timing']}):</b>\n"
            f"• <i>Визуал:</i> {s['climax']['visual']}\n"
            f"• <i>Озвучка:</i> «{s['climax']['voiceover']}»\n\n"
            f"🎯 <b>ПРИЗЫВ ({s['cta']['timing']}):</b>\n"
            f"• <i>Визуал:</i> {s['cta']['visual']}\n"
            f"• <i>Озвучка:</i> «{s['cta']['voiceover']}»"
        )
        await callback.message.answer(script_text, parse_mode="HTML")
        
    await callback.message.answer(
        "💡 <i>Снимайте видео с экрана телефона, показывая бота и WebApp — такая нативная органика конвертит лучше всего!</i>",
        parse_mode="HTML",
        reply_markup=kb.get_back_to_partner()
    )
    await callback.answer()

@router.callback_query(F.data == "partner_gen_reel")
async def cb_partner_gen_reel(callback: CallbackQuery):
    user_id = callback.from_user.id
    bot_info = await callback.bot.get_me()
    partner = await db.get_partner(user_id) or {}
    slug = partner.get("partner_code", str(user_id))
    
    await callback.answer("⏳ Создаем видео с живыми данными и вашим тегом... Это займет ~15-30 сек.")
    status_msg = await callback.message.answer("🎬 <b>Рендеринг брендированного видеоролика...</b>\n\nРассчитываем котировки, анимируем график и накладываем дикторскую озвучку 🎙", parse_mode="HTML")
    
    try:
        chan_tag = partner.get("channel_name") or f"Код: {slug}"
        video_path = await traffic_funnel.generate_branded_teaser_reel(
            bot_username=bot_info.username,
            channel_tag=f"Партнер: @{slug}",
            symbol="BTCUSDT",
            partner_code=slug
        )
        
        if os.path.exists(video_path):
            await status_msg.edit_text("📤 Видео создано! Загружаем в Telegram...")
            video_file = FSInputFile(video_path)
            caption = (
                f"🎥 <b>Ваш готовый вирусный видео-тизер готов!</b>\n\n"
                f"• Формат: 9:16 Full HD (Reels, Shorts, TikTok, Telegram Stories)\n"
                f"• Вшита плашка с вашим тегом бота: <code>@{bot_info.username}</code>\n"
                f"• Ваш партнерский код: <code>{slug}</code>\n\n"
                f"Скачайте это видео и опубликуйте его в Reels/Shorts со своей реферальной ссылкой в описании!"
            )
            await callback.message.answer_video(video=video_file, caption=caption, parse_mode="HTML", reply_markup=kb.get_back_to_partner())
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Ошибка: файл видео не найден на сервере.", reply_markup=kb.get_back_to_partner())
    except Exception as e:
        await status_msg.edit_text(
            f"ℹ️ <b>Генератор видео:</b>\n"
            f"Используйте сценарии из раздела «🎬 Сценарии Reels» для ручной съемки или запустите `generate_reel.py` на сервере.\n"
            f"<i>Технические детали: {str(e)[:100]}</i>",
            parse_mode="HTML",
            reply_markup=kb.get_back_to_partner()
        )

