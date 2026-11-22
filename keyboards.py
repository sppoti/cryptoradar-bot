import os
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import config
from services import knowledge_base

def get_tma_url(user_id: int = None, is_vip: bool = False, coin: str = None) -> str:
    """Формирует URL для запуска Telegram Mini App с параметрами авторизации и API."""
    base = config.WEBAPP_URL or "https://sppoti.github.io/cryptoradar-tma/"
    params = []
    if user_id and "user_id=" not in base:
        params.append(f"user_id={user_id}")
    if is_vip and "vip=" not in base:
        params.append("vip=1")
    if coin and "symbol=" not in base:
        params.append(f"symbol={coin}")
    if "api=" not in base:
        api_url = os.getenv("RENDER_EXTERNAL_URL", "https://cryptoradar-bot-z1r3.onrender.com")
        if api_url:
            params.append(f"api={api_url}")
    
    if not params:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{'&'.join(params)}"

def get_main_menu(is_admin: bool = False, user_id: int = None, is_vip: bool = False) -> InlineKeyboardMarkup:
    """Главное меню бота с доступом к сервисам и Telegram Mini App."""
    webapp_url = get_tma_url(user_id=user_id, is_vip=is_vip)
    webapp_text = "📱 Открыть WebApp Терминал (PRO VIP)" if is_vip else "📱 Открыть WebApp Терминал (PRO)"
    tariffs_text = "⭐ Продлить VIP-доступ" if is_vip else "💎 Оформить VIP-доступ"

    buttons = [
        [InlineKeyboardButton(text=webapp_text, web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton(text="🔐 Перейти в VIP-канал", callback_data="enter_vip_channel")],
        [InlineKeyboardButton(text=tariffs_text, callback_data="tariffs")],
        [
            InlineKeyboardButton(text="🌐 Обзор рынка (Live)", callback_data="market_overview"),
            InlineKeyboardButton(text="📊 Анализ монеты", callback_data="coin_select")
        ],
        [
            InlineKeyboardButton(text="🚨 Радар сигналов (RSI)", callback_data="signal_radar"),
            InlineKeyboardButton(text="📚 База знаний", callback_data="kb_list")
        ],
        [
            InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile"),
            InlineKeyboardButton(text="🤝 Партнерам (30% Rev-Share)", callback_data="partner_dashboard")
        ],
        [
            InlineKeyboardButton(text="🎁 Бесплатные дни", callback_data="referrals"),
            InlineKeyboardButton(text="🏆 Турнир рефералов", callback_data="leaderboard")
        ],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👑 Панель Администратора", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_webapp_keyboard(user_id: int = None, is_vip: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для прямого запуска Telegram Mini App терминала."""
    webapp_url = get_tma_url(user_id=user_id, is_vip=is_vip)
    webapp_text = "🚀 Запустить WebApp Терминал (PRO VIP)" if is_vip else "🚀 Запустить WebApp Терминал"
    tariffs_text = "⭐ Продлить VIP-доступ" if is_vip else "💎 Оформить VIP-доступ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=webapp_text, web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton(text="🔐 Перейти в VIP-канал", callback_data="enter_vip_channel")],
        [InlineKeyboardButton(text=tariffs_text, callback_data="tariffs")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])

def get_coin_selection_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для быстрого выбора актива."""
    buttons = [
        [
            InlineKeyboardButton(text="Bitcoin (BTC)", callback_data="analyze_BTCUSDT"),
            InlineKeyboardButton(text="Ethereum (ETH)", callback_data="analyze_ETHUSDT")
        ],
        [
            InlineKeyboardButton(text="Solana (SOL)", callback_data="analyze_SOLUSDT"),
            InlineKeyboardButton(text="Toncoin (TON)", callback_data="analyze_TONUSDT")
        ],
        [
            InlineKeyboardButton(text="BNB", callback_data="analyze_BNBUSDT"),
            InlineKeyboardButton(text="Ripple (XRP)", callback_data="analyze_XRPUSDT"),
            InlineKeyboardButton(text="Dogecoin (DOGE)", callback_data="analyze_DOGEUSDT")
        ],
        [InlineKeyboardButton(text="🔍 Ввести свою монету", callback_data="custom_coin")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_custom_coin_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура при вводе своей монеты."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К выбору монет", callback_data="coin_select")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])

def get_analysis_result_keyboard(symbol: str = "") -> InlineKeyboardMarkup:
    """Клавиатура под отчетом анализа монеты."""
    buttons = []
    if symbol:
        buttons.append([
            InlineKeyboardButton(text="🧠 Глубокий AI-прогноз", callback_data=f"ai_forecast_{symbol}"),
            InlineKeyboardButton(text="🖼 Карточка сигнала", callback_data=f"card_{symbol}")
        ])
    buttons.extend([
        [
            InlineKeyboardButton(text="🔄 Другая монета", callback_data="coin_select"),
            InlineKeyboardButton(text="🔍 Ввести тикер", callback_data="custom_coin")
        ],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_ai_forecast_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """Клавиатура под отчетом AI-прогноза (Task 3)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Обновить прогноз", callback_data=f"ai_forecast_{symbol}"),
            InlineKeyboardButton(text="📊 Экспресс-RSI", callback_data=f"analyze_{symbol}")
        ],
        [
            InlineKeyboardButton(text="🖼 Карточка сигнала", callback_data=f"card_{symbol}")
        ],
        [
            InlineKeyboardButton(text="🔍 Другой актив", callback_data="coin_select"),
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
        ]
    ])

def get_signal_card_keyboard(symbol: str = "") -> InlineKeyboardMarkup:
    """Клавиатура под сгенерированной визуальной карточкой сигнала."""
    buttons = []
    if symbol:
        buttons.append([
            InlineKeyboardButton(text="🔄 Обновить карточку", callback_data=f"card_{symbol}"),
            InlineKeyboardButton(text="🧠 AI-прогноз", callback_data=f"ai_forecast_{symbol}")
        ])
    buttons.extend([
        [
            InlineKeyboardButton(text="📊 Экспресс-RSI", callback_data=f"analyze_{symbol}" if symbol else "coin_select"),
            InlineKeyboardButton(text="🔍 Другой актив", callback_data="coin_select")
        ],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)



def get_knowledge_base_keyboard() -> InlineKeyboardMarkup:
    """Список обучающих статей для VIP."""
    articles = knowledge_base.get_articles_list()
    buttons = []
    for art in articles:
        buttons.append([InlineKeyboardButton(text=art["title"], callback_data=f"read_{art['id']}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_vip_teaser_keyboard() -> InlineKeyboardMarkup:
    """Кнопки в тизере при попытке зайти без подписки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Оформить VIP-подписку", callback_data="tariffs")],
        [InlineKeyboardButton(text="🎁 Получить доступ бесплатно (Рефералы)", callback_data="referrals")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu")]
    ])

def get_tariffs_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура со списком тарифов (только Telegram Stars)."""
    buttons = []
    for key, data in config.TARIFFS.items():
        text = f"{data['title']} — {data['stars']} ⭐"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"tariff_{key}")])
        
    buttons.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payment_methods(tariff_key: str) -> InlineKeyboardMarkup:
    """Выбор способа оплаты для конкретного тарифа (только Telegram Stars)."""
    tariff = config.TARIFFS.get(tariff_key)
    stars = tariff["stars"] if tariff else 0
    
    buttons = [
        [InlineKeyboardButton(text=f"⭐ Оплатить Telegram Stars ({stars} ⭐)", callback_data=f"pay_stars_{tariff_key}")],
        [InlineKeyboardButton(text="⬅️ К списку тарифов", callback_data="tariffs")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payment_success_keyboard(vip_link: str = None, user_id: int = None, is_vip: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура после успешной оплаты с моментальным доступом в WebApp."""
    vip_btn = (
        InlineKeyboardButton(text="🔐 Перейти в VIP-канал", url=vip_link)
        if vip_link
        else InlineKeyboardButton(text="🔐 Перейти в VIP-канал", callback_data="enter_vip_channel")
    )
    webapp_url = get_tma_url(user_id=user_id, is_vip=is_vip)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть WebApp Терминал PRO", web_app=WebAppInfo(url=webapp_url))],
        [vip_btn],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])

def get_leaderboard_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура турнира рефералов."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Получить свою ссылку", callback_data="referrals")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])

def get_back_to_menu() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])

def get_admin_panel() -> InlineKeyboardMarkup:
    """Панель администратора."""
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика и доходы", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🤝 B2B Партнеры и выплаты", callback_data="admin_partners")],
        [InlineKeyboardButton(text="🔐 Статус закрытого VIP-канала", callback_data="admin_vip_channel_status")],
        [InlineKeyboardButton(text="📢 Сделать рассылку по всем", callback_data="admin_broadcast")],
        [
            InlineKeyboardButton(text="🎯 Тест: VIP Сигнал", callback_data="admin_test_vip_setup"),
            InlineKeyboardButton(text="🌅 Тест: VIP Брифинг", callback_data="admin_test_vip_morning")
        ],
        [InlineKeyboardButton(text="🐋 Тест: Whale Алерт", callback_data="admin_test_vip_whale")],
        [
            InlineKeyboardButton(text="🚀 Сводка рынка в канал", callback_data="admin_post_channel"),
            InlineKeyboardButton(text="📰 Опубликовать новость", callback_data="admin_post_news")
        ],
        [InlineKeyboardButton(text="⚡️ Flash-Алерт в канал", callback_data="admin_post_alert")],
        [InlineKeyboardButton(text="➕ Выдать доступ вручную", callback_data="admin_grant")],
        [InlineKeyboardButton(text="⬅️ Выйти в главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_vip_channel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления закрытым VIP-каналом в админке."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить статус", callback_data="admin_vip_channel_status")],
        [InlineKeyboardButton(text="🧹 Исключить истекшие подписки", callback_data="admin_kick_expired")],
        [
            InlineKeyboardButton(text="🎯 Тест: VIP Сигнал", callback_data="admin_test_vip_setup"),
            InlineKeyboardButton(text="🌅 Тест: VIP Брифинг", callback_data="admin_test_vip_morning")
        ],
        [InlineKeyboardButton(text="🐋 Тест: Whale Алерт", callback_data="admin_test_vip_whale")],
        [InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="admin_panel")]
    ])

def get_profile_keyboard(has_active_sub: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура профиля пользователя с кнопкой входа в VIP-канал."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Перейти в VIP-канал", callback_data="enter_vip_channel")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])

def get_confirm_payment_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    """Кнопки для подтверждения чека администратором."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm_approve_{payment_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_reject_{payment_id}")
        ]
    ])

# ==================== КЛАВИАТУРЫ ДЛЯ B2B ПАРТНЕРОВ ====================

def get_partner_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура кабинета партнера."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Запросить вывод средств", callback_data="partner_payout_select")],
        [
            InlineKeyboardButton(text="📢 Готовые промо-посты", callback_data="partner_promo_posts"),
            InlineKeyboardButton(text="🎬 Сценарии Reels/TikTok", callback_data="partner_promo_reels")
        ],
        [
            InlineKeyboardButton(text="🎥 Создать промо-видео", callback_data="partner_gen_reel"),
            InlineKeyboardButton(text="🏷 Свой реф-код (slug)", callback_data="partner_set_slug")
        ],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]
    ])

def get_partner_payout_currency_keyboard() -> InlineKeyboardMarkup:
    """Выбор валюты для вывода."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="payout_curr_XTR"),
            InlineKeyboardButton(text="💳 Рубли (СБП/Карта)", callback_data="payout_curr_RUB")
        ],
        [InlineKeyboardButton(text="⬅️ Назад в кабинет", callback_data="partner_dashboard")]
    ])

def get_back_to_partner() -> InlineKeyboardMarkup:
    """Кнопка возврата в партнерский кабинет."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В кабинет партнера", callback_data="partner_dashboard")]
    ])

def get_admin_partners_keyboard(has_pending: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура управления партнерами в админ-панели."""
    buttons = []
    if has_pending:
        buttons.append([InlineKeyboardButton(text="📋 Заявки на выплату (Ожидают)", callback_data="admin_payouts_list")])
    buttons.append([InlineKeyboardButton(text="🔄 Обновить сводку", callback_data="admin_partners")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_payout_approval_keyboard(payout_id: int) -> InlineKeyboardMarkup:
    """Кнопки одобрения / отклонения заявки на выплату."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить выплату", callback_data=f"adm_pay_app_{payout_id}"),
            InlineKeyboardButton(text="❌ Отклонить (возврат)", callback_data=f"adm_pay_rej_{payout_id}")
        ]
    ])

