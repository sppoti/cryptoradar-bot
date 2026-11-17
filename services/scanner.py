import aiohttp
import asyncio
import html
import re
from typing import Dict, Any, List, Optional

BINANCE_API_URL = "https://api.binance.com/api/v3"

# Список отслеживаемых популярных активов
TOP_SYMBOLS = [
    ("BTCUSDT", "Bitcoin", "BTC"),
    ("ETHUSDT", "Ethereum", "ETH"),
    ("SOLUSDT", "Solana", "SOL"),
    ("TONUSDT", "Toncoin", "TON"),
    ("BNBUSDT", "BNB", "BNB"),
    ("XRPUSDT", "Ripple", "XRP"),
    ("DOGEUSDT", "Dogecoin", "DOGE")
]

async def fetch_json(url: str) -> Optional[Any]:
    """Асинхронный HTTP GET запрос."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        print(f"Ошибка запроса к {url}: {e}")
    return None

async def get_ticker_24hr(symbol: str) -> Optional[Dict[str, Any]]:
    """Получить 24ч статистику по монете."""
    url = f"{BINANCE_API_URL}/ticker/24hr?symbol={symbol.upper()}"
    return await fetch_json(url)

async def get_top_market_tickers(limit: int = 10) -> List[Dict[str, Any]]:
    """Получить топ-активы по объему торгов и динамике за 24ч с Binance."""
    url = f"{BINANCE_API_URL}/ticker/24hr"
    data = await fetch_json(url)
    if not isinstance(data, list):
        return []
        
    stables = {"USDCUSDT", "FDUSDUSDT", "BUSDUSDT", "TUSDUSDT", "EURUSDT", "DAIUSDT", "USDPUSDT"}
    usdt_tickers = [
        t for t in data
        if isinstance(t, dict)
        and str(t.get("symbol", "")).endswith("USDT")
        and t.get("symbol") not in stables
    ]
    try:
        usdt_tickers.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
    except Exception:
        pass
    return usdt_tickers[:limit]

# Маппинг распространенных кириллических омоглифов на латиницу (для защиты от случайного ввода в русской раскладке)
CYRILLIC_LOOKALIKES = {
    'А': 'A', 'В': 'B', 'С': 'C', 'Е': 'E', 'Н': 'H', 'К': 'K',
    'М': 'M', 'О': 'O', 'Р': 'P', 'Т': 'T', 'Х': 'X', 'У': 'Y'
}
CYRILLIC_TRANS_TABLE = str.maketrans(CYRILLIC_LOOKALIKES)

async def calculate_rsi(symbol: str, interval: str = "1h", period: int = 14) -> Optional[float]:
    """Рассчитать индекс относительной силы (RSI)."""
    url = f"{BINANCE_API_URL}/klines?symbol={symbol.upper()}&interval={interval}&limit={period + 15}"
    candles = await fetch_json(url)
    if not isinstance(candles, list) or len(candles) < period + 1:
        return None
        
    try:
        closes = [float(c[4]) for c in candles if isinstance(c, (list, tuple)) and len(c) > 4]
        if len(closes) < period + 1:
            return None
    except Exception:
        return None

    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
            
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 1)

def format_price(val: float) -> str:
    """Форматирование цены с учетом порядка величины."""
    if val >= 100:
        return f"${val:,.2f}"
    elif val >= 1:
        return f"${val:.2f}"
    elif val >= 0.0001:
        return f"${val:.4f}"
    elif val >= 0.00000001:
        res = f"${val:.8f}".rstrip("0")
        return res if res != "$0." else "$0.00"
    elif val > 0:
        res = f"${val:.10f}".rstrip("0")
        return res if res != "$0." else "$0.00"
    else:
        return "$0.00"

def normalize_symbol(raw_ticker: str) -> Optional[str]:
    """
    Нормализует введенный пользователем тикер для Binance API.
    Примеры:
      'btc' -> 'BTCUSDT'
      'BTCUSDT' -> 'BTCUSDT'
      'btc/usdt' -> 'BTCUSDT'
      'btc-usdt' -> 'BTCUSDT'
      '$sol' -> 'SOLUSDT'
      '  eth  ' -> 'ETHUSDT'
      '1000pepe' -> '1000PEPEUSDT'
      'w' -> 'WUSDT'
      'ВТС' (русская раскладка) -> 'BTCUSDT'
    Возвращает строку формата 'BTCUSDT' или None, если ввод некорректен.
    """
    if not raw_ticker or not isinstance(raw_ticker, str):
        return None

    s = raw_ticker.strip().upper()
    # Заменяем кириллические омоглифы
    s = s.translate(CYRILLIC_TRANS_TABLE)
    # Удаляем ведущие знаки $, #
    s = re.sub(r"^[\$#]+", "", s)
    # Удаляем распространенные разделители торговых пар: /, -, _, ., пробелы
    s = re.sub(r"[\s/\-_\.]+", "", s)

    # Проверка на допустимые символы: только латинские буквы и цифры (от 1 до 20)
    # Поддерживает как 1-символьные тикеры Binance (W, S, G, T), так и длинные (1000PEPE)
    if not re.fullmatch(r"[A-Z0-9]{1,20}", s):
        return None

    # Если тикер не заканчивается на USDT, добавляем USDT
    if not s.endswith("USDT"):
        s += "USDT"

    # Если тикер просто USDT или USDTUSDT, это некорректный базовый актив
    if s == "USDT" or s == "USDTUSDT":
        return None

    return s

async def check_symbol_exists(symbol: str) -> bool:
    """Проверяет существование торговой пары на Binance."""
    data = await get_ticker_24hr(symbol)
    return data is not None and isinstance(data, dict) and "lastPrice" in data

async def get_coin_analysis(symbol: str, name: str = "") -> str:
    """Генерация комплексного теханализа монеты."""
    ticker = await get_ticker_24hr(symbol)
    base_name = symbol[:-4] if symbol.endswith("USDT") else symbol
    if not ticker or not isinstance(ticker, dict) or "lastPrice" not in ticker:
        return (
            f"❌ <b>Монета {html.escape(base_name)} ({html.escape(symbol)}) не найдена на бирже Binance.</b>\n\n"
            f"Пожалуйста, убедитесь, что актив торгуется в паре к USDT (например, <code>BTC</code>, <code>SOL</code> или <code>PEPE</code>), и проверьте правильность тикера."
        )
        
    try:
        price = float(ticker.get("lastPrice") or 0)
        change_pct = float(ticker.get("priceChangePercent") or 0)
        high = float(ticker.get("highPrice") or 0)
        low = float(ticker.get("lowPrice") or 0)
        raw_vol = float(ticker.get("quoteVolume") or 0)
        volume = raw_vol / 1_000_000  # в млн $
    except (ValueError, TypeError):
        price = change_pct = high = low = volume = raw_vol = 0.0
    
    rsi_1h = await calculate_rsi(symbol, "1h", 14)
    rsi_4h = await calculate_rsi(symbol, "4h", 14)
    
    # Формируем вердикт на основе RSI и динамики (с явной проверкой is not None)
    if rsi_1h is not None and rsi_1h <= 32:
        verdict = "🟢 <b>СИЛЬНЫЙ СИГНАЛ НА ПОКУПКУ (Oversold)</b>\n<i>Актив перепродан на таймфрейме 1ч, высокая вероятность отскока вверх.</i>"
    elif rsi_1h is not None and rsi_1h >= 68:
        verdict = "🔴 <b>СИГНАЛ НА ФИКСАЦИЮ / ШОРТ (Overbought)</b>\n<i>Актив перекуплен, высока вероятность коррекции вниз.</i>"
    elif change_pct > 3:
        verdict = "📈 <b>ВОСХОДЯЩИЙ ИМПУЛЬС (Бычий тренд)</b>\n<i>Уверенный рост при умеренном RSI.</i>"
    elif change_pct < -3:
        verdict = "📉 <b>НИСХОДЯЩИЙ ТРЕНД (Медвежье давление)</b>\n<i>Актив под давлением продавцов.</i>"
    else:
        verdict = "⚪ <b>НЕЙТРАЛЬНЫЙ БОКОВИК (Консолидация)</b>\n<i>Рынок в ожидании импульса. Лучше торговать от границ диапазона.</i>"

    # Форматирование цены
    price_str = format_price(price)
    high_str = format_price(high)
    low_str = format_price(low)
    change_emoji = "🟢 +" if change_pct >= 0 else "🔴 "

    if volume >= 1:
        vol_str = f"${volume:,.1f}M"
    elif volume >= 0.001:
        vol_str = f"${volume * 1000:,.1f}K"
    else:
        vol_str = f"${raw_vol:,.0f}"
    
    rsi_1h_display = f"{rsi_1h:.1f}" if rsi_1h is not None else "—"
    rsi_4h_display = f"{rsi_4h:.1f}" if rsi_4h is not None else "—"
    if rsi_1h is not None:
        if rsi_1h < 35:
            rsi_1h_status = " (Перепродан 🟢)"
        elif rsi_1h > 65:
            rsi_1h_status = " (Перекуплен 🔴)"
        else:
            rsi_1h_status = " (Нейтрально ⚪)"
    else:
        rsi_1h_status = ""

    report = (
        f"📊 <b>Экспресс-анализ: {html.escape(base_name)} / USDT</b>\n"
        f"────────────────────\n"
        f"💵 <b>Текущая цена:</b> <code>{price_str}</code>\n"
        f"📈 <b>Изменение за 24ч:</b> <b>{change_emoji}{change_pct:.2f}%</b>\n"
        f"🔼 <b>Максимум 24ч:</b> {high_str}\n"
        f"🔽 <b>Минимум 24ч:</b> {low_str}\n"
        f"💧 <b>Объем торгов:</b> {vol_str}\n\n"
        f"🧭 <b>Технические индикаторы:</b>\n"
        f"• Индикатор RSI (1h): <b>{rsi_1h_display}</b>{rsi_1h_status}\n"
        f"• Индикатор RSI (4h): <b>{rsi_4h_display}</b>\n\n"
        f"🎯 <b>Вердикт сканера:</b>\n{verdict}\n"
        f"────────────────────\n"
        f"<i>Данные обновлены в реальном времени с биржи Binance.</i>"
    )
    return report

async def get_market_overview() -> str:
    """Сводка по всему рынку криптовалют."""
    lines = []
    lines.append("🌐 <b>Обзор рынка в реальном времени:</b>\n")
    
    tasks = [get_ticker_24hr(sym) for sym, _, _ in TOP_SYMBOLS]
    results = await asyncio.gather(*tasks)
    
    for (sym, name, ticker_name), data in zip(TOP_SYMBOLS, results):
        if not data:
            continue
        price = float(data.get("lastPrice", 0))
        chg = float(data.get("priceChangePercent", 0))
        emoji = "🟢" if chg >= 0 else "🔴"
        p_str = f"${price:,.2f}" if price >= 1 else f"${price:.4f}"
        lines.append(f"{emoji} <b>{ticker_name}</b>: <code>{p_str}</code> (<b>{chg:+.2f}%</b>)")
        
    lines.append("\n💡 <i>Для детального разбора актива нажмите «📊 Анализ монеты» в меню.</i>")
    return "\n".join(lines)

async def get_signal_radar() -> str:
    """Сканер аномалий и сигналов по топ активам."""
    lines = ["🚨 <b>Радар сигналов перекупленности / перепроданности (RSI 1ч):</b>\n"]
    found_signals = False
    
    for sym, name, ticker_name in TOP_SYMBOLS:
        rsi = await calculate_rsi(sym, "1h", 14)
        if rsi is None:
            continue
            
        if rsi <= 35:
            found_signals = True
            lines.append(f"🟢 <b>{ticker_name} (RSI: {rsi})</b> — <b>СИГНАЛ В ЛОНГ</b> (Сильная перепроданность, зона набора позиций)")
        elif rsi >= 65:
            found_signals = True
            lines.append(f"🔴 <b>{ticker_name} (RSI: {rsi})</b> — <b>СИГНАЛ В ШОРТ / ФИКСАЦИЯ</b> (Перекупленность, риск коррекции)")
            
    if not found_signals:
        lines.append("⚪ <b>Экстремальных отклонений нет.</b>\nВсе топовые активы находятся в нейтральном диапазоне RSI (35-65). Рынок стабилен.")
        
    lines.append("\n<i>Сканер автоматически отслеживает таймфрейм 1 час и выявляет точки входа.</i>")
    return "\n".join(lines)

async def check_flash_anomaly() -> Optional[Dict[str, Any]]:
    """Поиск резких пампов, дампов или аномалий RSI среди отслеживаемых активов."""
    import database as db
    
    EXTENDED_SYMBOLS = TOP_SYMBOLS + [
        ("PEPEUSDT", "Pepe", "PEPE"),
        ("NEARUSDT", "NEAR Protocol", "NEAR"),
        ("SUIUSDT", "Sui", "SUI"),
        ("ADAUSDT", "Cardano", "ADA")
    ]
    
    for sym, name, ticker_name in EXTENDED_SYMBOLS:
        ticker = await get_ticker_24hr(sym)
        if not ticker:
            continue
            
        chg = float(ticker.get("priceChangePercent", 0))
        price = float(ticker.get("lastPrice", 0))
        rsi_1h = await calculate_rsi(sym, "1h", 14)
        
        alert_type = None
        headline = ""
        verdict = ""
        
        if chg >= 5.0 or (rsi_1h and rsi_1h >= 72):
            alert_type = "PUMP"
            headline = f"🚀 <b>PUMP ALERT: #{ticker_name} показывает резкий рост!</b>"
            verdict = "Импульсный рост объема. Наблюдается перекупленность (RSI > 70) — вероятен тест максимумов или фиксация."
        elif chg <= -5.0 or (rsi_1h and rsi_1h <= 30):
            alert_type = "DUMP"
            headline = f"📉 <b>DIP ALERT: #{ticker_name} вошел в зону перепроданности!</b>"
            verdict = "Сильное давление продавцов прижало RSI к критическому уровню. Высокая вероятность отскока вверх от поддержки."
            
        if alert_type and await db.can_post_alert(sym, alert_type, cooldown_hours=2):
            await db.record_alert(sym, alert_type)
            p_str = f"${price:,.2f}" if price >= 1 else f"${price:.6f}"
            return {
                "symbol": ticker_name,
                "headline": headline,
                "price": p_str,
                "change": f"{chg:+.2f}%",
                "rsi": rsi_1h or 50.0,
                "verdict": verdict
            }
            
    return None

async def get_ai_forecast(symbol: str) -> Dict[str, Any]:
    """Получить комплексный ИИ-прогноз и продвинутую аналитику по активу (Task 3)."""
    from services import ai_analytics
    return await ai_analytics.get_ai_market_forecast(symbol)


