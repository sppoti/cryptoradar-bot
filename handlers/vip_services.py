import html
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest, ChatMemberUpdated
from aiogram.filters import Command
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database as db
import keyboards as kb
from services import scanner, knowledge_base, ai_analytics, vip_channel

router = Router()

class CustomCoinState(StatesGroup):
    waiting_for_ticker = State()

def get_vip_teaser_text() -> str:
    """Текст предложения оформить VIP-подписку для аналитических инструментов."""
    sub_1m = config.TARIFFS.get("sub_1m", {"rub_price": 150, "stars": 150})
    return (
        "🔒 <b>Инструмент «Экспресс-анализ монеты» доступен только для VIP-участников!</b>\n\n"
        "📌 <b>Что получает подписчик:</b>\n"
        "• Мгновенный расчет индикаторов <b>RSI (1h и 4h)</b> в реальном времени\n"
        "• Определение зон экстремальной перекупленности и перепроданности\n"
        "• Торговый вердикт (Лонг / Шорт / Накопление) без задержек\n"
        "• Экспресс-анализ <b>любой собственной монеты</b> на бирже Binance\n"
        "• Доступ в закрытый VIP-канал с ежедневными рекомендациями\n\n"
        f"💎 Оформите подписку от {sub_1m['stars']} ⭐ ниже (мгновенная авто-выдача), чтобы разблокировать доступ:"
    )

@router.callback_query(F.data == "market_overview")
async def cb_market_overview(callback: CallbackQuery):
    """Сводка рынка доступна всем как лид-магнит."""
    loading_msg = await callback.message.edit_text("⏳ <i>Опрашиваем биржу и рассчитываем котировки...</i>", parse_mode="HTML")
    overview = await scanner.get_market_overview()
    await callback.message.edit_text(overview, parse_mode="HTML", reply_markup=kb.get_back_to_menu())
    await callback.answer()

@router.callback_query(F.data == "coin_select")
async def cb_coin_select(callback: CallbackQuery, state: FSMContext):
    """Выбор монеты для анализа (требует VIP подписки)."""
    await state.clear()
    user_id = callback.from_user.id
    is_active = await db.is_sub_active(user_id)
    
    if not is_active:
        await callback.message.edit_text(get_vip_teaser_text(), parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        await callback.answer()
        return
        
    text = (
        "📊 <b>Экспресс-анализ криптовалют (VIP):</b>\n\n"
        "Выберите актив из списка популярных монет или нажмите <b>«🔍 Ввести свою монету»</b>, чтобы указать любой тикер на Binance:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_coin_selection_keyboard())
    await callback.answer()

@router.callback_query(F.data == "custom_coin")
async def cb_custom_coin(callback: CallbackQuery, state: FSMContext):
    """Запрос ввода собственного тикера от VIP-пользователя."""
    user_id = callback.from_user.id
    is_active = await db.is_sub_active(user_id)
    
    if not is_active:
        await state.clear()
        await callback.message.edit_text(get_vip_teaser_text(), parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        await callback.answer()
        return
        
    await state.set_state(CustomCoinState.waiting_for_ticker)
    text = (
        "🔍 <b>Анализ собственной монеты:</b>\n\n"
        "Отправьте тикер монеты текстовым сообщением.\n"
        "Например: <code>BTC</code>, <code>ETH</code>, <code>SOL</code>, <code>PEPE</code>, <code>NEAR</code> или <code>BTCUSDT</code>.\n\n"
        "<i>Поддерживаются любые торговые пары к USDT на бирже Binance.</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_custom_coin_keyboard())
    await callback.answer()

@router.message(CustomCoinState.waiting_for_ticker, Command("cancel"))
async def cmd_cancel_custom_coin(message: Message, state: FSMContext):
    """Отмена ввода тикера."""
    await state.clear()
    await message.answer("Ввод тикера отменен.", reply_markup=kb.get_coin_selection_keyboard())

@router.message(CustomCoinState.waiting_for_ticker, F.text, ~F.text.startswith("/"))
async def process_custom_coin_ticker(message: Message, state: FSMContext):
    """Обработка ввода произвольного тикера VIP-пользователем."""
    user_id = message.from_user.id
    is_active = await db.is_sub_active(user_id)
    
    if not is_active:
        await state.clear()
        await message.answer(get_vip_teaser_text(), parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        return
        
    raw_ticker = message.text.strip()
    symbol = scanner.normalize_symbol(raw_ticker)
    if not symbol:
        await message.answer(
            "❌ <b>Некорректный формат тикера.</b>\n\n"
            "Пожалуйста, введите тикер латинскими буквами (например: <code>BTC</code>, <code>SOL</code>, <code>PEPE</code> или <code>ETHUSDT</code>):",
            parse_mode="HTML",
            reply_markup=kb.get_custom_coin_keyboard()
        )
        return
        
    loading = await message.answer(f"⏳ <i>Получаем данные по <b>{html.escape(symbol)}</b> с Binance и рассчитываем RSI...</i>", parse_mode="HTML")
    try:
        report = await scanner.get_coin_analysis(symbol)
        await loading.edit_text(report, parse_mode="HTML", reply_markup=kb.get_analysis_result_keyboard(symbol))
    except Exception:
        await loading.edit_text(
            f"❌ <b>Ошибка при получении данных по активу {html.escape(symbol)}.</b>\nПожалуйста, попробуйте позже.",
            parse_mode="HTML",
            reply_markup=kb.get_analysis_result_keyboard(symbol)
        )
    finally:
        await state.clear()

@router.message(CustomCoinState.waiting_for_ticker, ~F.text.startswith("/"))
async def process_invalid_ticker_content(message: Message):
    """Обработка неподдерживаемого типа контента при ожидании тикера."""
    await message.answer(
        "❌ Пожалуйста, отправьте текстовое сообщение с тикером монеты (например: <code>BTC</code>, <code>SOL</code>).",
        parse_mode="HTML",
        reply_markup=kb.get_custom_coin_keyboard()
    )

@router.message(Command("analyze", "coin"))
async def cmd_analyze_coin(message: Message, state: FSMContext):
    """Команда прямого запроса анализа монеты (только для VIP)."""
    user_id = message.from_user.id
    is_active = await db.is_sub_active(user_id)
    
    if not is_active:
        await state.clear()
        await message.answer(get_vip_teaser_text(), parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        return
        
    raw_text = message.text or message.caption or ""
    args = raw_text.split(maxsplit=1)
    if len(args) > 1 and args[1].strip():
        raw_ticker = args[1].strip()
        symbol = scanner.normalize_symbol(raw_ticker)
        if not symbol:
            await message.answer(
                "❌ <b>Некорректный формат тикера.</b>\n\n"
                "Пример использования: <code>/analyze BTC</code> или <code>/analyze SOL</code>",
                parse_mode="HTML",
                reply_markup=kb.get_custom_coin_keyboard()
            )
            return
            
        loading = await message.answer(f"⏳ <i>Получаем данные по <b>{html.escape(symbol)}</b> с Binance и рассчитываем RSI...</i>", parse_mode="HTML")
        try:
            report = await scanner.get_coin_analysis(symbol)
            await loading.edit_text(report, parse_mode="HTML", reply_markup=kb.get_analysis_result_keyboard(symbol))
        except Exception:
            await loading.edit_text(
                f"❌ <b>Ошибка при получении данных по активу {html.escape(symbol)}.</b>\nПожалуйста, попробуйте позже.",
                parse_mode="HTML",
                reply_markup=kb.get_analysis_result_keyboard(symbol)
            )
        finally:
            await state.clear()
    else:
        await state.set_state(CustomCoinState.waiting_for_ticker)
        text = (
            "🔍 <b>Анализ собственной монеты:</b>\n\n"
            "Отправьте тикер монеты текстовым сообщением.\n"
            "Например: <code>BTC</code>, <code>ETH</code>, <code>SOL</code>, <code>PEPE</code>, <code>NEAR</code> или <code>BTCUSDT</code>.\n\n"
            "<i>Поддерживаются любые торговые пары к USDT на бирже Binance.</i>"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=kb.get_custom_coin_keyboard())

@router.callback_query(F.data.startswith("analyze_"))
async def cb_analyze_coin(callback: CallbackQuery):
    """Анализ конкретной монеты из списка предустановленных."""
    user_id = callback.from_user.id
    if not await db.is_sub_active(user_id):
        await callback.message.edit_text(get_vip_teaser_text(), parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        await callback.answer()
        return
        
    symbol = callback.data.replace("analyze_", "")
    await callback.message.edit_text("⏳ <i>Идет расчет свечей и индикатора RSI...</i>", parse_mode="HTML")
    
    try:
        report = await scanner.get_coin_analysis(symbol)
        await callback.message.edit_text(report, parse_mode="HTML", reply_markup=kb.get_analysis_result_keyboard(symbol))
    except Exception:
        await callback.message.edit_text("❌ Ошибка при получении данных с биржи.", reply_markup=kb.get_analysis_result_keyboard(symbol))
    finally:
        await callback.answer()

@router.callback_query(F.data.startswith("ai_forecast_"))
async def cb_ai_forecast(callback: CallbackQuery):
    """Глубокий ИИ-прогноз по монете (требует VIP, Task 3)."""
    user_id = callback.from_user.id
    if not await db.is_sub_active(user_id):
        await callback.message.edit_text(get_vip_teaser_text(), parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        await callback.answer()
        return

    symbol = callback.data.replace("ai_forecast_", "")
    base_ticker = symbol[:-4] if symbol.endswith("USDT") else symbol
    await callback.message.edit_text(
        f"🧠 <i>Запуск нейросетевого анализа Gemini & Multi-Timeframe Engine для <b>{html.escape(base_ticker)}</b>...</i>",
        parse_mode="HTML"
    )

    try:
        data = await ai_analytics.get_ai_market_forecast(symbol)
        text = ai_analytics.format_ai_forecast_telegram(data)
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_ai_forecast_keyboard(symbol))
    except Exception:
        await callback.message.edit_text(
            f"❌ <b>Ошибка при расчете ИИ-прогноза по {html.escape(symbol)}.</b> Пожалуйста, повторите позже.",
            parse_mode="HTML",
            reply_markup=kb.get_analysis_result_keyboard(symbol)
        )
    finally:
        await callback.answer()

@router.message(Command("ai_forecast", "forecast", "ai"))
async def cmd_ai_forecast(message: Message, state: FSMContext):
    """Команда прямого глубокого AI-прогноза: /forecast BTC или /ai SOL."""
    user_id = message.from_user.id
    if not await db.is_sub_active(user_id):
        await state.clear()
        await message.answer(get_vip_teaser_text(), parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        return

    raw_text = message.text or message.caption or ""
    args = raw_text.split(maxsplit=1)
    if len(args) > 1 and args[1].strip():
        raw_ticker = args[1].strip()
        symbol = scanner.normalize_symbol(raw_ticker)
        if not symbol:
            await message.answer(
                "❌ <b>Некорректный формат тикера.</b>\n\n"
                "Пример использования: <code>/forecast BTC</code> или <code>/ai SOL</code>",
                parse_mode="HTML",
                reply_markup=kb.get_custom_coin_keyboard()
            )
            return

        base_ticker = symbol[:-4] if symbol.endswith("USDT") else symbol
        loading = await message.answer(
            f"🧠 <i>Запуск нейросетевого анализа Gemini & Multi-Timeframe Engine для <b>{html.escape(base_ticker)}</b>...</i>",
            parse_mode="HTML"
        )
        try:
            data = await ai_analytics.get_ai_market_forecast(symbol)
            text = ai_analytics.format_ai_forecast_telegram(data)
            await loading.edit_text(text, parse_mode="HTML", reply_markup=kb.get_ai_forecast_keyboard(symbol))
        except Exception:
            await loading.edit_text(
                f"❌ <b>Ошибка при формировании ИИ-прогноза по {html.escape(symbol)}.</b>",
                parse_mode="HTML",
                reply_markup=kb.get_analysis_result_keyboard(symbol)
            )
        finally:
            await state.clear()
    else:
        text = (
            "🧠 <b>Глубокий ИИ-прогноз и продвинутая аналитика (VIP):</b>\n\n"
            "Укажите тикер актива через пробел, например: <code>/forecast BTC</code> или <code>/ai SOL</code>.\n"
            "Либо выберите актив из списка ниже для мгновенного анализа:"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=kb.get_coin_selection_keyboard())


@router.callback_query(F.data == "signal_radar")
async def cb_signal_radar(callback: CallbackQuery):
    """Радар сигналов рынка."""
    user_id = callback.from_user.id
    is_active = await db.is_sub_active(user_id)
    
    if not is_active:
        teaser_text = (
            "🔒 <b>«Радар сигналов RSI» закрыт для свободного доступа!</b>\n\n"
            "Этот модуль непрерывно сканирует рынок и находит активы, готовые к сильному развороту или импульсу.\n\n"
            "Получите доступ к сигналам по подписке:"
        )
        await callback.message.edit_text(teaser_text, parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        await callback.answer()
        return
        
    await callback.message.edit_text("⏳ <i>Сканируем топ-активы на предмет аномалий...</i>", parse_mode="HTML")
    radar_text = await scanner.get_signal_radar()
    await callback.message.edit_text(radar_text, parse_mode="HTML", reply_markup=kb.get_back_to_menu())
    await callback.answer()

@router.callback_query(F.data == "kb_list")
async def cb_kb_list(callback: CallbackQuery):
    """Закрытая база знаний."""
    user_id = callback.from_user.id
    is_active = await db.is_sub_active(user_id)
    
    if not is_active:
        teaser_text = (
            "🔒 <b>База знаний и стратегий доступна только участникам VIP-клуба!</b>\n\n"
            "Внутри собраны практические руководства по трейдингу, поиску скрытых гемов, риск-менеджменту и работе с китовыми объемами.\n\n"
            "Разблокируйте базу знаний прямо сейчас:"
        )
        await callback.message.edit_text(teaser_text, parse_mode="HTML", reply_markup=kb.get_vip_teaser_keyboard())
        await callback.answer()
        return
        
    text = "📚 <b>Закрытая база знаний и стратегий:</b>\n\nВыберите интересующий материал для изучения:"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_knowledge_base_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("read_"))
async def cb_read_article(callback: CallbackQuery):
    """Чтение конкретной статьи."""
    user_id = callback.from_user.id
    if not await db.is_sub_active(user_id):
        await callback.answer("Доступ только для VIP!", show_alert=True)
        return
        
    art_id = callback.data.replace("read_", "")
    article = knowledge_base.get_article(art_id)
    if not article:
        await callback.answer("Материал не найден.", show_alert=True)
        return
        
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К списку статей", callback_data="kb_list")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])
    await callback.message.edit_text(article["content"], parse_mode="HTML", reply_markup=buttons)
    await callback.answer()

# ==================== УПРАВЛЕНИЕ ЗАКРЫТЫМ VIP-КАНАЛОМ ====================

@router.chat_join_request()
async def cb_vip_join_request(event: ChatJoinRequest, bot: Bot):
    """Автоматическая обработка заявок на вступление в закрытый VIP-канал."""
    await vip_channel.process_join_request(event, bot)

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def cb_vip_member_joined(event: ChatMemberUpdated):
    """Фиксация прямого входа пользователя в закрытый VIP-канал по ссылке."""
    if vip_channel.is_vip_channel_configured() and str(event.chat.id) == str(config.VIP_CHANNEL_ID):
        await db.record_vip_channel_join(event.new_chat_member.user.id)
