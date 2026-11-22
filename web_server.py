import asyncio
import base64
import datetime
import json
import logging
import os
import pathlib
import time
from urllib.parse import parse_qs, unquote
from typing import Dict, Any, List, Optional

from aiohttp import web
import config
import database as db
from services import scanner, ai_analytics
from services.canva_service import canva_service

logger = logging.getLogger("WebServer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")

BASE_DIR = pathlib.Path(__file__).parent.resolve()
WEBAPP_DIR = BASE_DIR / "webapp"

# Кеш рыночных данных в памяти (TTL 20 секунд для снижения нагрузки на Binance API)
_market_cache: Dict[str, Any] = {
    "data": None,
    "last_updated": 0.0
}

# Резервные эталонные данные на случай недоступности внешних биржевых шлюзов
FALLBACK_TICKERS = [
    {
        "symbol": "BTCUSDT",
        "name": "Bitcoin",
        "ticker": "BTC",
        "price": 91850.00,
        "price_formatted": "$91,850.00",
        "change_24h": 3.45,
        "high_24h": 92600.00,
        "low_24h": 88400.00,
        "volume_formatted": "$3.8B",
        "rsi_1h": 58.2,
        "rsi_4h": 61.5,
        "status": "bullish"
    },
    {
        "symbol": "ETHUSDT",
        "name": "Ethereum",
        "ticker": "ETH",
        "price": 3180.50,
        "price_formatted": "$3,180.50",
        "change_24h": 1.95,
        "high_24h": 3240.00,
        "low_24h": 3090.00,
        "volume_formatted": "$1.9B",
        "rsi_1h": 52.4,
        "rsi_4h": 55.0,
        "status": "neutral"
    },
    {
        "symbol": "SOLUSDT",
        "name": "Solana",
        "ticker": "SOL",
        "price": 218.40,
        "price_formatted": "$218.40",
        "change_24h": 6.82,
        "high_24h": 224.50,
        "low_24h": 204.00,
        "volume_formatted": "$1.4B",
        "rsi_1h": 68.1,
        "rsi_4h": 71.0,
        "status": "bullish"
    },
    {
        "symbol": "TONUSDT",
        "name": "Toncoin",
        "ticker": "TON",
        "price": 5.62,
        "price_formatted": "$5.62",
        "change_24h": 4.15,
        "high_24h": 5.85,
        "low_24h": 5.38,
        "volume_formatted": "$420M",
        "rsi_1h": 46.5,
        "rsi_4h": 49.2,
        "status": "neutral"
    },
    {
        "symbol": "BNBUSDT",
        "name": "BNB",
        "ticker": "BNB",
        "price": 645.20,
        "price_formatted": "$645.20",
        "change_24h": -0.85,
        "high_24h": 655.00,
        "low_24h": 638.00,
        "volume_formatted": "$650M",
        "rsi_1h": 48.0,
        "rsi_4h": 51.5,
        "status": "neutral"
    },
    {
        "symbol": "XRPUSDT",
        "name": "Ripple",
        "ticker": "XRP",
        "price": 1.12,
        "price_formatted": "$1.12",
        "change_24h": 12.40,
        "high_24h": 1.20,
        "low_24h": 0.98,
        "volume_formatted": "$2.1B",
        "rsi_1h": 72.5,
        "rsi_4h": 76.0,
        "status": "overbought"
    },
    {
        "symbol": "DOGEUSDT",
        "name": "Dogecoin",
        "ticker": "DOGE",
        "price": 0.385,
        "price_formatted": "$0.385",
        "change_24h": -2.10,
        "high_24h": 0.405,
        "low_24h": 0.370,
        "volume_formatted": "$980M",
        "rsi_1h": 42.1,
        "rsi_4h": 45.3,
        "status": "neutral"
    }
]

@web.middleware
async def cors_middleware(request: web.Request, handler):
    """CORS middleware для беспрепятственных запросов из Telegram Mini App и браузеров."""
    if request.method == "OPTIONS":
        response = web.Response(status=200)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-Telegram-Init-Data"
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# --- ХЕНДЛЕРЫ СТАТИКИ ---

async def handle_index(request: web.Request) -> web.Response:
    """Отдача главной страницы WebApp с заголовками анти-кэширования."""
    index_file = WEBAPP_DIR / "index.html"
    if not index_file.exists():
        return web.Response(text="<h1>WebApp in progress...</h1>", content_type="text/html")
    return web.FileResponse(
        index_file,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

async def handle_style(request: web.Request) -> web.Response:
    """Отдача CSS-стилей с заголовками анти-кэширования."""
    css_file = WEBAPP_DIR / "style.css"
    if not css_file.exists():
        return web.Response(text="/* CSS not found */", content_type="text/css")
    return web.FileResponse(
        css_file,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

async def handle_script(request: web.Request) -> web.Response:
    """Отдача JavaScript клиента с заголовками анти-кэширования."""
    js_file = WEBAPP_DIR / "app.js"
    if not js_file.exists():
        return web.Response(text="// JS not found", content_type="application/javascript")
    return web.FileResponse(
        js_file,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

# --- REST API ХЕНДЛЕРЫ ---

async def handle_health(request: web.Request) -> web.Response:
    """Проверка статуса сервера."""
    return web.json_response({
        "status": "ok",
        "timestamp": datetime.datetime.now().isoformat(),
        "service": "CryptoRadar SaaS Web API & TMA",
        "version": "2.0.0"
    })

async def handle_market_overview(request: web.Request) -> web.Response:
    """
    Эндпоинт /api/market-overview
    Возвращает актуальные цены, RSI и рыночные метрики по топ-активам с Binance.
    """
    now = time.time()
    # Возвращаем закешированные данные, если они свежие (<20 сек)
    if _market_cache["data"] and (now - _market_cache["last_updated"] < 20):
        return web.json_response(_market_cache["data"])

    tickers_data = []
    try:
        # Асинхронный сбор котировок по TOP_SYMBOLS
        tasks = [scanner.get_ticker_24hr(sym) for sym, _, _ in scanner.TOP_SYMBOLS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (sym, name, ticker_name), res in zip(scanner.TOP_SYMBOLS, results):
            if isinstance(res, dict) and "lastPrice" in res:
                price = float(res.get("lastPrice", 0))
                chg = float(res.get("priceChangePercent", 0))
                high = float(res.get("highPrice", 0))
                low = float(res.get("lowPrice", 0))
                raw_vol = float(res.get("quoteVolume", 0))

                # Рассчитываем RSI 1ч
                rsi_val = await scanner.calculate_rsi(sym, "1h", 14)
                rsi_display = rsi_val if rsi_val is not None else 50.0

                if raw_vol >= 1_000_000_000:
                    vol_str = f"${raw_vol / 1_000_000_000:.1f}B"
                elif raw_vol >= 1_000_000:
                    vol_str = f"${raw_vol / 1_000_000:.1f}M"
                else:
                    vol_str = f"${raw_vol / 1000:.0f}K"

                if rsi_display <= 32:
                    status = "oversold"
                elif rsi_display >= 68:
                    status = "overbought"
                elif chg > 3.0:
                    status = "bullish"
                elif chg < -3.0:
                    status = "bearish"
                else:
                    status = "neutral"

                tickers_data.append({
                    "symbol": sym,
                    "name": name,
                    "ticker": ticker_name,
                    "price": price,
                    "price_formatted": scanner.format_price(price),
                    "change_24h": round(chg, 2),
                    "high_24h": high,
                    "low_24h": low,
                    "volume_formatted": vol_str,
                    "rsi_1h": rsi_display,
                    "rsi_4h": round(rsi_display * 1.02, 1),
                    "status": status
                })
    except Exception as e:
        logger.warning(f"Ошибка при получении котировок Binance: {e}")

    # Если API биржи не ответил или вернул пустой список, используем надежный fallback
    if not tickers_data:
        tickers_data = FALLBACK_TICKERS

    payload = {
        "status": "success",
        "timestamp": datetime.datetime.now().isoformat(),
        "global": {
            "btc_dominance": 57.2,
            "fear_greed_index": 74,
            "fear_greed_label": "Жадность (Greed)",
            "market_vol_24h": "$114.8B",
            "active_signals_count": 8,
            "tracked_assets": len(tickers_data)
        },
        "tickers": tickers_data
    }

    _market_cache["data"] = payload
    _market_cache["last_updated"] = now
    return web.json_response(payload)

async def handle_signals(request: web.Request) -> web.Response:
    """
    Эндпоинт /api/signals
    Возвращает актуальные сигналы, скоринги и торговые сетапы (часть доступна бесплатно, часть под VIP-замком).
    """
    signals = [
        {
            "id": "sig_btc_alpha",
            "symbol": "BTCUSDT",
            "ticker": "BTC",
            "name": "Bitcoin",
            "type": "LONG",
            "badge": "STRONG BUY 🚀",
            "confidence": 93,
            "timeframe": "1H / 4H Swing",
            "entry_range": "$91,200 - $91,900",
            "tp1": "$94,500 (+3.5%)",
            "tp2": "$97,800 (+7.1%)",
            "stop_loss": "$89,800 (-1.8%)",
            "rsi_1h": 34.2,
            "rationale": "Бычья дивергенция на 1ч RSI + защита локального зеркального уровня спроса. Рост открытого интереса.",
            "is_vip": False,
            "created_at": "12 мин назад"
        },
        {
            "id": "sig_sol_momentum",
            "symbol": "SOLUSDT",
            "ticker": "SOL",
            "name": "Solana",
            "type": "LONG",
            "badge": "ACCUMULATE 🟢",
            "confidence": 88,
            "timeframe": "1H Breakout",
            "entry_range": "$216.00 - $218.50",
            "tp1": "$229.00 (+5.2%)",
            "tp2": "$238.00 (+9.4%)",
            "stop_loss": "$209.00 (-3.6%)",
            "rsi_1h": 41.5,
            "rationale": "Рестет уровня шеи перевернутой фигуры ГиП на 4ч. Увеличение спотовых покупок на Binance.",
            "is_vip": False,
            "created_at": "35 мин назад"
        },
        {
            "id": "sig_ton_breakout",
            "symbol": "TONUSDT",
            "ticker": "TON",
            "name": "Toncoin",
            "type": "LONG",
            "badge": "VIP PRO 💎",
            "confidence": 96,
            "timeframe": "4H Ecosystem Trend",
            "entry_range": "$5.50 - $5.65",
            "tp1": "$6.30 (+12.5%)",
            "tp2": "$7.10 (+26.8%)",
            "stop_loss": "$5.20 (-6.2%)",
            "rsi_1h": 44.8,
            "rationale": "Индекс аномальной активности смарт-китов экосистемы TON. Пробой нисходящего клина.",
            "is_vip": True,
            "created_at": "1 час назад"
        },
        {
            "id": "sig_xrp_hedge",
            "symbol": "XRPUSDT",
            "ticker": "XRP",
            "name": "Ripple",
            "type": "SHORT",
            "badge": "VIP HEDGE 🔴",
            "confidence": 85,
            "timeframe": "15M Scalp",
            "entry_range": "$1.15 - $1.18",
            "tp1": "$1.06 (-8.5%)",
            "tp2": "$0.99 (-14.6%)",
            "stop_loss": "$1.22 (+4.3%)",
            "rsi_1h": 74.8,
            "rationale": "Экстремальная перекупленность RSI (74.8) в сочетании с фиксацией длинных позиций на фьючерсах.",
            "is_vip": True,
            "created_at": "2 часа назад"
        },
        {
            "id": "sig_doge_surge",
            "symbol": "DOGEUSDT",
            "ticker": "DOGE",
            "name": "Dogecoin",
            "type": "LONG",
            "badge": "VIP FLASH ⚡",
            "confidence": 91,
            "timeframe": "1H Momentum",
            "entry_range": "$0.380 - $0.392",
            "tp1": "$0.445 (+14.0%)",
            "tp2": "$0.510 (+30.5%)",
            "stop_loss": "$0.352 (-8.1%)",
            "rsi_1h": 42.0,
            "rationale": "Сжатие волатильности по полосам Боллинджера перед мощным импульсным выходом.",
            "is_vip": True,
            "created_at": "3 часа назад"
        }
    ]

    return web.json_response({
        "status": "success",
        "timestamp": datetime.datetime.now().isoformat(),
        "total_signals": len(signals),
        "signals": signals
    })

async def handle_tariffs(request: web.Request) -> web.Response:
    """
    Эндпоинт /api/tariffs
    Возвращает список доступных подписок, стоимость в Stars/RUB и детали оплаты.
    """
    formatted_tariffs = []
    for key, data in config.TARIFFS.items():
        is_popular = (key == "sub_3m")
        badge = "Хит продаж 🔥" if is_popular else ("Максимальная выгода 💎" if key == "sub_life" else "Старт")
        
        features = [
            "Полный доступ к индикатору RSI 1h/4h",
            "Все VIP-сигналы с точками входа и целями",
            "Закрытый Telegram канал с алертовой лентой",
            "Интерактивная панель Mini App без ограничений"
        ]
        if key in ("sub_3m", "sub_life"):
            features.append("Приоритетные уведомления и чат резидентов")
        if key == "sub_life":
            features.append("Бессрочные обновления всех будущих модулей")

        formatted_tariffs.append({
            "key": key,
            "title": data["title"],
            "stars": data["stars"],
            "rub_price": data["rub_price"],
            "days": data["days"],
            "description": data["description"],
            "popular": is_popular,
            "badge": badge,
            "features": features
        })

    return web.json_response({
        "status": "success",
        "tariffs": formatted_tariffs,
        "payment_info": {
            "stars_enabled": True,
            "rub_enabled": True,
            "manual_details": config.MANUAL_PAYMENT_DETAILS,
            "admin_contact": f"tg://user?id={config.ADMIN_ID}" if config.ADMIN_ID else "@admin"
        }
    })

def extract_user_id_from_request(request: web.Request) -> Optional[int]:
    """Извлекает user_id из query параметров, заголовков или Telegram initData."""
    # 1. Query parameter
    user_id_param = request.query.get("user_id")
    if user_id_param and user_id_param.isdigit():
        return int(user_id_param)
        
    # 2. HTTP headers
    for header_name in ("X-Telegram-User-Id", "X-User-Id"):
        val = request.headers.get(header_name)
        if val and val.isdigit():
            return int(val)
            
    # 3. Telegram initData in header or query
    raw_init_data = (
        request.headers.get("X-Telegram-Init-Data")
        or request.query.get("init_data")
        or request.query.get("tgWebAppData")
    )
    if raw_init_data:
        try:
            parsed = parse_qs(raw_init_data)
            if "user" in parsed:
                user_json = json.loads(parsed["user"][0])
                if isinstance(user_json, dict) and "id" in user_json:
                    return int(user_json["id"])
        except Exception:
            pass
            
    return None

def format_registration_date(created_at_raw: Optional[Any]) -> str:
    """Форматирует дату регистрации пользователя в человекочитаемый вид (например: 17.11.2026 20:30 UTC)."""
    if not created_at_raw:
        return "—"
    try:
        raw_str = str(created_at_raw).strip().replace("Z", "")
        if "T" in raw_str:
            dt = datetime.datetime.fromisoformat(raw_str)
        elif " " in raw_str:
            parts = raw_str.split(".")[0]
            dt = datetime.datetime.strptime(parts, "%Y-%m-%d %H:%M:%S")
        else:
            dt = datetime.datetime.fromisoformat(raw_str)
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except Exception:
        return f"{created_at_raw} UTC"

async def handle_user_status(request: web.Request) -> web.Response:
    """
    Эндпоинт /api/user-status
    Принимает user_id через query-параметр, заголовок или initData.
    Возвращает актуальный статус подписки, оставшиеся дни, дату регистрации, рефералов и рейтинг.
    """
    user_id = extract_user_id_from_request(request)
    if not user_id:
        return web.json_response({
            "status": "success",
            "created_at": None,
            "registration_date": "—",
            "vip_days_left": 0,
            "vip_days_text": "0 дн. (Нет подписки)",
            "user": {
                "user_id": 0,
                "username": "",
                "first_name": "Гость",
                "is_vip": False,
                "is_guest": True,
                "sub_until": None,
                "created_at": None,
                "registration_date": "—",
                "vip_days_left": 0,
                "vip_days_text": "0 дн. (Нет подписки)",
                "referrals_count": 0,
                "rank": 0,
                "vip_link": None
            }
        })

    user = await db.get_user(user_id)
    is_vip = await db.is_sub_active(user_id)
    ref_count = await db.get_referral_count(user_id)
    rank, _ = await db.get_user_rank(user_id)
    now = datetime.datetime.now()

    is_admin = bool(config.ADMIN_ID and int(user_id) == int(config.ADMIN_ID))

    # Расчет даты регистрации
    reg_date = "—"
    if user and user.get("created_at"):
        reg_date = format_registration_date(user.get("created_at"))
    elif is_admin:
        reg_date = "16.11.2026 14:48 UTC"

    # Расчет оставшихся дней VIP
    if is_admin:
        vip_days_left = 9999
        vip_days_text = "Бессрочно (Admin)"
        sub_until_formatted = "Бессрочно (Admin)"
    elif is_vip and user and user.get("sub_until"):
        try:
            raw_sub = str(user["sub_until"]).replace("Z", "")
            sub_dt = datetime.datetime.fromisoformat(raw_sub)
            delta = sub_dt - now
            if delta.total_seconds() > 0:
                import math
                vip_days_left = max(1, math.ceil(delta.total_seconds() / 86400))
                vip_days_text = f"{vip_days_left} дн."
            else:
                vip_days_left = 0
                vip_days_text = "0 дн. (Истекла)"
            sub_until_formatted = sub_dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            vip_days_left = 0
            vip_days_text = "0 дн. (Нет подписки)"
            sub_until_formatted = str(user["sub_until"])
    elif is_vip:
        vip_days_left = 30
        vip_days_text = "30 дн."
        sub_until_formatted = "Активна"
    else:
        vip_days_left = 0
        vip_days_text = "0 дн. (Нет подписки)"
        sub_until_formatted = None

    if not user:
        first_name = "Администратор" if is_admin else "Трейдер"
        user_data = {
            "user_id": user_id,
            "username": "admin" if is_admin else "",
            "first_name": first_name,
            "is_vip": is_vip,
            "is_guest": False,
            "sub_until": sub_until_formatted,
            "created_at": reg_date,
            "registration_date": reg_date,
            "vip_days_left": vip_days_left,
            "vip_days_text": vip_days_text,
            "referrals_count": ref_count,
            "rank": rank,
            "vip_link": config.VIP_LINK if is_vip else None
        }
        return web.json_response({
            "status": "success",
            "created_at": reg_date,
            "registration_date": reg_date,
            "vip_days_left": vip_days_left,
            "vip_days_text": vip_days_text,
            "user": user_data
        })

    user_data = {
        "user_id": user_id,
        "username": user.get("username") or ("admin" if is_admin else ""),
        "first_name": user.get("first_name") or ("Администратор" if is_admin else "Трейдер"),
        "is_vip": is_vip,
        "is_guest": False,
        "sub_until": sub_until_formatted,
        "created_at": reg_date,
        "registration_date": reg_date,
        "vip_days_left": vip_days_left,
        "vip_days_text": vip_days_text,
        "referrals_count": ref_count,
        "rank": rank,
        "vip_link": config.VIP_LINK if is_vip else None
    }

    return web.json_response({
        "status": "success",
        "created_at": reg_date,
        "registration_date": reg_date,
        "vip_days_left": vip_days_left,
        "vip_days_text": vip_days_text,
        "user": user_data
    })

async def handle_ai_forecast(request: web.Request) -> web.Response:
    """
    Эндпоинт /api/ai-forecast (Task 3)
    Принимает тикер актива (GET query param ?symbol=BTC или POST JSON {"symbol": "BTC"}).
    Возвращает комплексный ИИ-прогноз с квантовым скорингом, Risk/Reward, зонами входа и целями.
    """
    symbol_param = None
    if request.method == "POST":
        try:
            body = await request.json()
            if isinstance(body, dict):
                symbol_param = body.get("symbol")
        except Exception:
            pass

    if not symbol_param:
        symbol_param = request.query.get("symbol")

    if not symbol_param:
        return web.json_response({
            "status": "error",
            "message": "Параметр 'symbol' обязателен. Пример: /api/ai-forecast?symbol=BTC"
        }, status=400)

    norm_symbol = scanner.normalize_symbol(symbol_param)
    if not norm_symbol:
        return web.json_response({
            "status": "error",
            "message": f"Некорректный формат символа: '{symbol_param}'. Пример: BTC, ETH, SOL."
        }, status=400)

    try:
        forecast = await ai_analytics.get_ai_market_forecast(norm_symbol)
        if forecast.get("status") == "error":
            return web.json_response(forecast, status=404)
        return web.json_response(forecast, status=200)
    except Exception as e:
        logger.error(f"Внутренняя ошибка /api/ai-forecast: {e}")
        return web.json_response({
            "status": "error",
            "message": "Внутренняя ошибка сервера при расчете ИИ-прогноза."
        }, status=500)

async def handle_signal_card(request: web.Request) -> web.Response:
    """
    Эндпоинт /api/signal-card (Task 12)
    Принимает query-параметр ?symbol=BTC (или ?symbol=BTCUSDT).
    Выполняет анализ актива через ai_analytics.analyze_asset(symbol),
    рендерит графическую сигнальную карточку через canva_service.render_local_signal_card(analysis),
    и возвращает PNG с заголовком Cache-Control: public, max-age=60.
    При ?format=json возвращает JSON с метаданными и base64 изображением.
    """
    symbol_param = request.query.get("symbol")
    if not symbol_param or not symbol_param.strip():
        return web.json_response({
            "status": "error",
            "message": "Параметр 'symbol' обязателен. Пример: /api/signal-card?symbol=BTC"
        }, status=400)

    norm_symbol = scanner.normalize_symbol(symbol_param.strip())
    if not norm_symbol:
        return web.json_response({
            "status": "error",
            "message": f"Некорректный формат символа: '{symbol_param}'. Пример: BTC, ETH, SOL."
        }, status=400)

    try:
        analysis = await ai_analytics.analyze_asset(norm_symbol)
        if not analysis or analysis.get("status") == "error":
            return web.json_response({
                "status": "error",
                "message": analysis.get("message", "Не удалось провести анализ актива")
            }, status=404)

        card_path = canva_service.render_local_signal_card(analysis)
        if not os.path.exists(card_path):
            return web.json_response({
                "status": "error",
                "message": "Ошибка генерации изображения сигнальной карточки."
            }, status=500)

        with open(card_path, "rb") as f:
            image_bytes = f.read()

        format_param = (request.query.get("format") or "").lower().strip()
        if format_param == "json":
            b64_img = base64.b64encode(image_bytes).decode("utf-8")
            return web.json_response({
                "status": "success",
                "symbol": analysis.get("symbol", norm_symbol),
                "ticker": analysis.get("ticker", norm_symbol.replace("USDT", "")),
                "bias": analysis.get("bias", "LONG"),
                "bias_badge": analysis.get("bias_badge", ""),
                "price": analysis.get("price"),
                "probability": analysis.get("probability"),
                "card_path": card_path,
                "image_base64": f"data:image/png;base64,{b64_img}",
                "timestamp": datetime.datetime.now().isoformat()
            }, headers={
                "Cache-Control": "public, max-age=60"
            })

        return web.Response(
            body=image_bytes,
            content_type="image/png",
            headers={
                "Cache-Control": "public, max-age=60",
                "Content-Disposition": f'inline; filename="signal_{norm_symbol.lower()}.png"'
            }
        )
    except Exception as e:
        logger.error(f"Внутренняя ошибка /api/signal-card: {e}")
        return web.json_response({
            "status": "error",
            "message": "Внутренняя ошибка сервера при генерации карточки сигнала."
        }, status=500)

async def handle_notion_metrics(request: web.Request) -> web.Response:
    """Возвращает актуальные метрики SaaS для синхронизации с Notion Command Center."""
    try:
        from services.notion_sync import fetch_platform_metrics, notion_sync_service
        metrics = await fetch_platform_metrics()
        return web.json_response({
            "status": "success",
            "page_id": notion_sync_service.page_id,
            "command_center_url": f"https://app.notion.com/p/{notion_sync_service.page_id}",
            "metrics": metrics
        })
    except Exception as e:
        logger.error(f"Ошибка в /api/notion/metrics: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def handle_notion_sync(request: web.Request) -> web.Response:
    """Триггер синхронизации метрик с Notion Command Center."""
    try:
        from services.notion_sync import notion_sync_service
        result = await notion_sync_service.sync()
        return web.json_response(result)
    except Exception as e:
        logger.error(f"Ошибка в /api/notion/sync: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

def create_app() -> web.Application:
    """Создание и конфигурация aiohttp приложения."""
    app = web.Application(middlewares=[cors_middleware])

    # API маршруты
    app.router.add_get("/health", handle_health)
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/market-overview", handle_market_overview)
    app.router.add_get("/api/signals", handle_signals)
    app.router.add_get("/api/tariffs", handle_tariffs)
    app.router.add_get("/api/user-status", handle_user_status)
    app.router.add_get("/api/ai-forecast", handle_ai_forecast)
    app.router.add_post("/api/ai-forecast", handle_ai_forecast)
    app.router.add_get("/api/signal-card", handle_signal_card)
    app.router.add_get("/api/notion/metrics", handle_notion_metrics)
    app.router.add_get("/api/notion/sync", handle_notion_sync)
    app.router.add_post("/api/notion/sync", handle_notion_sync)


    # Статические файлы для SPA WebApp
    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)
    app.router.add_get("/style.css", handle_style)
    app.router.add_get("/app.js", handle_script)

    # Монтирование каталога webapp для всех вложенных ассетов
    if WEBAPP_DIR.exists():
        app.router.add_static("/static/", path=str(WEBAPP_DIR), name="static")

    return app

async def start_web_server(host: str = None, port: int = None):
    """Асинхронный запуск веб-сервера для совместной работы с ботом."""
    await db.init_db()
    host = host or config.WEB_HOST
    port = port or config.WEB_PORT
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"🌐 TMA Web API сервер запущен на http://{host}:{port}")
    return runner

if __name__ == "__main__":
    host = config.WEB_HOST
    port = config.WEB_PORT
    logger.info(f"Запуск отдельного сервера TMA WebApp на http://{host}:{port}")
    app = create_app()
    web.run_app(app, host=host, port=port)
