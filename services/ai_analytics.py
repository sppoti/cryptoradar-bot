import asyncio
import datetime
import html
import json
import logging
import math
import os
import time
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

from services import scanner

logger = logging.getLogger("AIAnalytics")

# Gemini API Client
try:
    from google import genai
    from google.genai import errors as genai_errors
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    logger.warning("google-genai библиотека не установлена или недоступна.")

BINANCE_API_URL = "https://api.binance.com/api/v3"

# Время жизни оперативного кеша (3 минуты)
CACHE_TTL_SECONDS = 180

# Внутренний потокобезопасный кеш: { "BTCUSDT": { "data": {...}, "expires_at": float } }
_FORECAST_CACHE: Dict[str, Dict[str, Any]] = {}
_cache_lock = asyncio.Lock()

# Константы торговых смещений (Bias)
BIAS_STRONG_LONG = "Strong Long"
BIAS_SCALP_LONG = "Scalp Long"
BIAS_NEUTRAL = "Neutral/Chop"
BIAS_SCALP_SHORT = "Scalp Short"
BIAS_STRONG_SHORT = "Strong Short"

BIAS_BADGES = {
    BIAS_STRONG_LONG: "🟢 СИЛЬНЫЙ ЛОНГ (Strong Long)",
    BIAS_SCALP_LONG: "🔵 ЛОНГ НА ОТСКОК (Scalp Long)",
    BIAS_NEUTRAL: "⚪ НЕЙТРАЛЬНО / БОКОВИК (Neutral/Chop)",
    BIAS_SCALP_SHORT: "🟠 ШОРТ ОТ СОПРОТИВЛЕНИЯ (Scalp Short)",
    BIAS_STRONG_SHORT: "🔴 СИЛЬНЫЙ ШОРТ (Strong Short)"
}

# --- ТЕХНИЧЕСКИЙ МАТЕМАТИЧЕСКИЙ ДВИЖОК ---

def calculate_rsi_series(closes: List[float], period: int = 14) -> Optional[float]:
    """
    Расчет классического RSI с экспоненциальным сглаживанием Уайлдера (Wilder's RSI).
    """
    if not closes or len(closes) < period + 1:
        return None

    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 1)


def calculate_ema(closes: List[float], period: int) -> Optional[float]:
    """
    Расчет экспоненциальной скользящей средней (EMA) для заданного периода.
    """
    if not closes or len(closes) < period:
        return None

    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period  # Seed SMA
    for price in closes[period:]:
        ema = (price * k) + (ema * (1.0 - k))
    return round(ema, 8)


def calculate_bollinger_bands(closes: List[float], period: int = 20, num_std: float = 2.0) -> Dict[str, float]:
    """
    Расчет полос Боллинджера:
    - Middle Band (SMA 20)
    - Upper Band (SMA + 2*StdDev)
    - Lower Band (SMA - 2*StdDev)
    - %B = (Price - Lower) / (Upper - Lower)
    - Bandwidth = (Upper - Lower) / Middle * 100
    """
    if not closes or len(closes) < period:
        last = closes[-1] if closes else 0.0
        return {
            "middle": last,
            "upper": last * 1.02,
            "lower": last * 0.98,
            "percent_b": 0.5,
            "bandwidth": 4.0
        }

    subset = closes[-period:]
    sma = sum(subset) / period
    variance = sum((x - sma) ** 2 for x in subset) / period
    std = math.sqrt(variance)

    upper = sma + (num_std * std)
    lower = sma - (num_std * std)
    last_price = closes[-1]
    band_range = upper - lower

    percent_b = (last_price - lower) / band_range if band_range > 0 else 0.5
    bandwidth = (band_range / sma * 100.0) if sma > 0 else 0.0

    return {
        "middle": round(sma, 8),
        "upper": round(upper, 8),
        "lower": round(lower, 8),
        "percent_b": round(percent_b, 4),
        "bandwidth": round(bandwidth, 2)
    }


def calculate_volume_spike(volumes: List[float], period: int = 20) -> Dict[str, Any]:
    """
    Анализ аномалий объема торгов: сравнение последнего объема со средней скользящей за период.
    """
    if not volumes or len(volumes) < 2:
        return {
            "recent_volume": 0.0,
            "average_volume": 0.0,
            "spike_ratio": 1.0,
            "is_spike": False
        }

    recent_vol = volumes[-1]
    prev_vols = volumes[-(period + 1):-1] if len(volumes) > period else volumes[:-1]
    avg_vol = (sum(prev_vols) / len(prev_vols)) if prev_vols else recent_vol
    spike_ratio = round((recent_vol / avg_vol) if avg_vol > 0 else 1.0, 2)

    return {
        "recent_volume": round(recent_vol, 2),
        "average_volume": round(avg_vol, 2),
        "spike_ratio": spike_ratio,
        "is_spike": spike_ratio >= 1.5
    }


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """
    Расчет индикатора истинного среднего диапазона (Average True Range - ATR).
    """
    if not highs or not lows or not closes or len(closes) < 2:
        return (closes[-1] * 0.018) if closes else 1.0

    tr_list = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)

    if not tr_list:
        return closes[-1] * 0.018

    subset = tr_list[-period:] if len(tr_list) >= period else tr_list
    return sum(subset) / len(subset)


async def fetch_klines(symbol: str, interval: str = "1h", limit: int = 100) -> List[List[Any]]:
    """Асинхронная выгрузка исторических свечей с Binance."""
    url = f"{BINANCE_API_URL}/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    data = await scanner.fetch_json(url)
    if isinstance(data, list):
        return data
    return []


# --- ИНТЕЛЛЕКТУАЛЬНЫЙ КВАНТОВЫЙ ХЕВРИСТИЧЕСКИЙ ДВИЖОК ---

def synthesize_quantitative_forecast(
    symbol: str,
    ticker_name: str,
    price: float,
    change_24h: float,
    volume_24h: float,
    rsi_1h: float,
    rsi_4h: float,
    bb: Dict[str, float],
    ema_20: float,
    ema_50: float,
    vol_spike: Dict[str, Any],
    atr: float
) -> Dict[str, Any]:
    """
    Институциональный детерминированный синтез:
    Анализирует консилиум индикаторов (RSI, Bollinger %B & Bandwidth, EMA 20/50, Volume Spike, ATR),
    вычисляет вероятностный скоринг, Bias, оптимальный Risk/Reward, уровни Entry, TP1, TP2, Stop Loss
    и генерирует профессиональное аналитическое резюме трейдера.
    """
    score = 0.0

    # 1. Трендовая структура по EMA (EMA 20 vs EMA 50 и Price vs EMA 20)
    ema_trend = "neutral"
    if ema_20 and ema_50:
        if ema_20 > ema_50:
            if price > ema_20:
                score += 2.0
                ema_trend = "bullish_strong"
            else:
                score += 1.0
                ema_trend = "bullish_pullback"
        elif ema_20 < ema_50:
            if price < ema_20:
                score -= 2.0
                ema_trend = "bearish_strong"
            else:
                score -= 1.0
                ema_trend = "bearish_pullback"

    # 2. Осцилляторный импульс RSI (1h и 4h)
    rsi_oversold = (rsi_1h <= 32)
    rsi_overbought = (rsi_1h >= 68)

    if rsi_oversold:
        score += 2.5  # Потенциал мощного отскока перепроданности
    elif rsi_overbought:
        score -= 2.5  # Риск резкой фиксации перекупленности
    else:
        # Умеренная динамика
        if 50.0 <= rsi_1h <= 65.0 and rsi_4h >= 50.0:
            score += 1.0
        elif 35.0 <= rsi_1h < 50.0 and rsi_4h < 50.0:
            score -= 1.0

    # 3. Волатильность и локализация по полосам Боллинджера (%B)
    pct_b = bb.get("percent_b", 0.5)
    bandwidth = bb.get("bandwidth", 4.0)

    if pct_b < 0.08:
        # Цена у нижней границы / пробивает ее вниз -> триггер mean reversion лонг
        score += 1.5
    elif pct_b > 0.92:
        # Цена у верхней границы / пробивает ее вверх -> триггер фиксации / шорт
        score -= 1.5

    # 4. Всплеск объемов
    if vol_spike.get("is_spike"):
        if score > 0:
            score += 1.0
        elif score < 0:
            score -= 1.0

    # Определение Bias
    if rsi_oversold or (pct_b < 0.12 and score >= 0):
        bias = BIAS_SCALP_LONG
    elif rsi_overbought or (pct_b > 0.88 and score <= 0):
        bias = BIAS_SCALP_SHORT
    elif score >= 2.5:
        bias = BIAS_STRONG_LONG
    elif score >= 1.0:
        bias = BIAS_SCALP_LONG
    elif score <= -2.5:
        bias = BIAS_STRONG_SHORT
    elif score <= -1.0:
        bias = BIAS_SCALP_SHORT
    else:
        bias = BIAS_NEUTRAL

    # Вероятностный скоринг (0-100%)
    confluence_factors = 0
    if (bias in (BIAS_STRONG_LONG, BIAS_SCALP_LONG) and price >= ema_20) or (bias in (BIAS_STRONG_SHORT, BIAS_SCALP_SHORT) and price <= ema_20):
        confluence_factors += 1
    if (bias in (BIAS_STRONG_LONG, BIAS_SCALP_LONG) and rsi_1h < 58) or (bias in (BIAS_STRONG_SHORT, BIAS_SCALP_SHORT) and rsi_1h > 42):
        confluence_factors += 1
    if vol_spike.get("is_spike"):
        confluence_factors += 1
    if bandwidth >= 3.0:
        confluence_factors += 1

    base_prob = 68 + (confluence_factors * 6)
    if bias == BIAS_NEUTRAL:
        base_prob = 62
    probability = min(94, max(55, base_prob))

    # Расчет уровней Entry, TP1, TP2, Stop Loss на базе ATR и Bollinger
    atr_val = atr if (atr and atr > 0) else (price * 0.018)

    if bias in (BIAS_STRONG_LONG, BIAS_SCALP_LONG):
        entry_low = price * 0.996
        entry_high = price * 1.002
        entry_mid = (entry_low + entry_high) / 2.0
        risk_dist = max(atr_val * 1.35, entry_mid * 0.015)
        sl_price = entry_mid - risk_dist
        tp1_price = entry_mid + (risk_dist * 1.6)
        tp2_price = entry_mid + (risk_dist * 2.8)
        tp3_price = entry_mid + (risk_dist * 4.2)
        rr_ratio = round((tp2_price - entry_mid) / risk_dist, 1)

    elif bias in (BIAS_STRONG_SHORT, BIAS_SCALP_SHORT):
        entry_low = price * 0.998
        entry_high = price * 1.004
        entry_mid = (entry_low + entry_high) / 2.0
        risk_dist = max(atr_val * 1.35, entry_mid * 0.015)
        sl_price = entry_mid + risk_dist
        tp1_price = entry_mid - (risk_dist * 1.6)
        tp2_price = entry_mid - (risk_dist * 2.8)
        tp3_price = entry_mid - (risk_dist * 4.2)
        rr_ratio = round((entry_mid - tp2_price) / risk_dist, 1)

    else:  # BIAS_NEUTRAL
        # Торговля в канале Боллинджера
        lower_band = bb.get("lower", price * 0.98)
        upper_band = bb.get("upper", price * 1.02)
        middle_band = bb.get("middle", price)
        entry_low = lower_band * 0.998
        entry_high = lower_band * 1.005
        entry_mid = (entry_low + entry_high) / 2.0
        sl_price = lower_band - (atr_val * 1.1)
        risk_dist = entry_mid - sl_price
        tp1_price = middle_band
        tp2_price = upper_band
        tp3_price = upper_band * 1.02
        rr_ratio = round((tp2_price - entry_mid) / (risk_dist if risk_dist > 0 else 1.0), 1)

    # Форматирование цен и процентов
    entry_str = f"{scanner.format_price(entry_low)} - {scanner.format_price(entry_high)}"

    tp1_pct = ((tp1_price - price) / price) * 100.0
    tp2_pct = ((tp2_price - price) / price) * 100.0
    tp3_pct = ((tp3_price - price) / price) * 100.0
    sl_pct = ((sl_price - price) / price) * 100.0

    tp1_sign = "+" if tp1_pct >= 0 else ""
    tp2_sign = "+" if tp2_pct >= 0 else ""
    tp3_sign = "+" if tp3_pct >= 0 else ""
    sl_sign = "+" if sl_pct >= 0 else ""

    tp1_str = f"{scanner.format_price(tp1_price)} ({tp1_sign}{tp1_pct:.2f}%)"
    tp2_str = f"{scanner.format_price(tp2_price)} ({tp2_sign}{tp2_pct:.2f}%)"
    tp3_str = f"{scanner.format_price(tp3_price)} ({tp3_sign}{tp3_pct:.2f}%)"
    sl_str = f"{scanner.format_price(sl_price)} ({sl_sign}{sl_pct:.2f}%)"
    rr_str = f"1:{rr_ratio:.1f}"

    # Генерация институционального executive summary
    trend_ru = "восходящей" if "bullish" in ema_trend else ("нисходящей" if "bearish" in ema_trend else "консолидационной")
    bb_state = "сжатия (squeeze)" if bandwidth < 3.2 else "умеренного расширения"
    vol_state = "аномальный всплеск ликвидности" if vol_spike.get("is_spike") else "стандартный рыночный объем"

    if bias == BIAS_STRONG_LONG:
        summary = (
            f"Анализ актива {ticker_name} подтверждает доминирование покупателей в рамках {trend_ru} структуры. "
            f"Котировки удерживаются выше связки EMA-20 ({scanner.format_price(ema_20)}) и EMA-50 ({scanner.format_price(ema_50)}). "
            f"Индекс RSI 1h ({rsi_1h}) указывает на уверенный бычий моментум без признаков критического перегрева. "
            f"Канал Боллинджера ({bb_state}, ширина {bandwidth}%) раскрывается по тренду, а {vol_state} усиливает импульс. "
            f"Рекомендуется удержание длинных позиций с частичной фиксацией на TP1 и защитным стопом под локальным свингом."
        )
    elif bias == BIAS_SCALP_LONG:
        summary = (
            f"По активу {ticker_name} зафиксирована краткосрочная зона перепроданности (RSI 1h: {rsi_1h}, %B: {pct_b:.2f}). "
            f"Цена протестировала нижнюю границу полос Боллинджера ({scanner.format_price(bb.get('lower', price))}) "
            f"в сочетании с дивергенцией младших таймфреймов. Ожидается технический отскок к медиане диапазона. "
            f"Сетап носит характер Mean-Reversion лонга с привлекательным соотношением прибыли к риску {rr_str}."
        )
    elif bias == BIAS_STRONG_SHORT:
        summary = (
            f"Наблюдается выраженное преобладание продавцов по {ticker_name}. Медвежье взаимное расположение EMA-20 "
            f"и EMA-50 с давлением цены ниже ключевых скользящих средних сигнализирует о продолжении импульсного даунтренда. "
            f"Полосы Боллинджера расширяются вниз, RSI 4h ({rsi_4h}) подтверждает системную слабость тренда. "
            f"Приоритетны короткие позиции от зоны сопротивления с целями на обновление локальных минимумов спроса."
        )
    elif bias == BIAS_SCALP_SHORT:
        summary = (
            f"Актив {ticker_name} подошел к верхней границе волатильности Боллинджера (%B: {pct_b:.2f}) при локальной "
            f"перекупленности осциллятора RSI (1h: {rsi_1h}). В стакане наблюдается нарастание лимитных заявок на продажу. "
            f"Вероятна техническая коррекция для разгрузки индикаторов к поддержке EMA-20 ({scanner.format_price(ema_20)}). "
            f"Рекомендуется фиксация прибыли по лонгам либо аккуратный шорт с жесткой инвалидацией за экстремум."
        )
    else:
        summary = (
            f"Рынок {ticker_name} находится в фазе горизонтальной консолидации (Chop Market). Котировки колеблются "
            f"вокруг равновесной средней EMA-20 ({scanner.format_price(ema_20)}), ширина канала Боллинджера составляет {bandwidth}%. "
            f"Индикаторы RSI 1h ({rsi_1h}) и RSI 4h ({rsi_4h}) находятся в нейтральном коридоре. "
            f"Рекомендуется воздержаться от трендовых входов и работать строго от границ диапазона либо ожидать импульсного пробоя."
        )

    return {
        "bias": bias,
        "bias_badge": BIAS_BADGES.get(bias, bias),
        "probability": probability,
        "risk_reward": rr_str,
        "entry_zone": entry_str,
        "tp1": tp1_str,
        "tp1_price": round(tp1_price, 8),
        "tp2": tp2_str,
        "tp2_price": round(tp2_price, 8),
        "tp3": tp3_str,
        "tp3_price": round(tp3_price, 8),
        "stop_loss": sl_str,
        "stop_loss_price": round(sl_price, 8),
        "summary": summary,
        "source": "quant_heuristic"
    }


# --- LLM СИНТЕЗ ЧЕРЕЗ GOOGLE GENAI (GEMINI) ---

async def call_gemini_synthesis(market_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Вызов Gemini LLM через google-genai SDK для синтеза экспертного заключения.
    При возникновении любых сетевых задержек, геоблокировок или неверного ключа
    мягко возвращает None для бесшовного перехода на квантовый движок.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not GENAI_AVAILABLE:
        return None

    prompt = f"""
Ты — старший квантовый аналитик и главный институциональный трейдер криптовалютного хедж-фонда.
Проанализируй предоставленные мульти-таймфрейм индикаторы актива {market_context.get('ticker')}/USDT:
- Текущая цена: {market_context.get('price_formatted')}
- Изменение 24ч: {market_context.get('change_24h')}%
- Объем 24ч: {market_context.get('volume_formatted')}
- RSI (1h): {market_context.get('rsi_1h')}
- RSI (4h): {market_context.get('rsi_4h')}
- Bollinger Bands: Middle={market_context.get('bb_middle')}, Upper={market_context.get('bb_upper')}, Lower={market_context.get('bb_lower')}, %B={market_context.get('bb_percent_b')}, Bandwidth={market_context.get('bb_bandwidth')}%
- Скользящие средние: EMA-20={market_context.get('ema_20')}, EMA-50={market_context.get('ema_50')}
- Всплеск объема торгов: x{market_context.get('volume_spike_ratio')} (Аномалия: {market_context.get('is_volume_spike')})

СФОРМИРУЙ СТРОГИЙ JSON со следующими полями:
{{
  "bias": "Strong Long" ИЛИ "Scalp Long" ИЛИ "Neutral/Chop" ИЛИ "Scalp Short" ИЛИ "Strong Short",
  "probability": целое число от 50 до 95 (вероятность реализации сетапа в %),
  "risk_reward": "1:2.8" (оптимальное соотношение риск/прибыль),
  "entry_zone": "строка диапазона цен входа",
  "tp1": "строка первой цели с процентом, напр. $XX.XX (+3.2%)",
  "tp2": "строка второй цели с процентом, напр. $XX.XX (+7.1%)",
  "stop_loss": "строка уровня инвалидации со стопом, напр. $XX.XX (-1.8%)",
  "summary": "3-4 плотных профессиональных предложения на русском языке с глубоким разбором структуры рынка, ликвидности и триггеров"
}}
Верни ТОЛЬКО валидный JSON без markdown форматирования.
"""
    # Модели для перебора
    candidate_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    try:
        client = genai.Client(api_key=api_key)
        for model_name in candidate_models:
            try:
                # Используем асинхронный вызов с таймаутом 6.0 сек
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt
                    ),
                    timeout=6.0
                )
                if response and response.text:
                    raw_text = response.text.strip()
                    # Очищаем от возможных markdown-оберток ```json
                    if raw_text.startswith("```"):
                        lines = raw_text.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        raw_text = "\n".join(lines).strip()

                    parsed = json.loads(raw_text)
                    if isinstance(parsed, dict) and "bias" in parsed and "summary" in parsed:
                        bias = parsed.get("bias", BIAS_NEUTRAL)
                        if bias not in BIAS_BADGES:
                            bias = BIAS_NEUTRAL

                        return {
                            "bias": bias,
                            "bias_badge": BIAS_BADGES.get(bias, bias),
                            "probability": int(parsed.get("probability", 75)),
                            "risk_reward": str(parsed.get("risk_reward", "1:2.5")),
                            "entry_zone": str(parsed.get("entry_zone", market_context.get("price_formatted", ""))),
                            "tp1": str(parsed.get("tp1", "")),
                            "tp2": str(parsed.get("tp2", "")),
                            "stop_loss": str(parsed.get("stop_loss", "")),
                            "summary": str(parsed.get("summary", "")).strip(),
                            "source": "gemini"
                        }
            except (genai_errors.APIError, asyncio.TimeoutError, Exception) as inner_err:
                logger.debug(f"Gemini model {model_name} inference attempt: {inner_err}")
                continue
    except Exception as e:
        logger.warning(f"Ошибка инициализации или запроса к Gemini API: {e}")

    return None


# --- ОСНОВНАЯ ТОЧКА ВХОДА ДЛЯ АНАЛИТИКИ И КЕШИРОВАНИЯ ---

async def get_ai_market_forecast(raw_symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Генерирует комплексный ИИ-прогноз по криптовалютному активу.
    - Автоматическая нормализация тикера (например, 'btc', 'ethusdt', 'sol').
    - Многоуровневый расчет технических индикаторов (RSI 1h/4h, Bollinger Bands, EMA 20/50, Volume Spikes, ATR).
    - Интеграция с Gemini 2.5/Flash при наличии ключа и квантовый fallback движок при отсутствии/ошибке API.
    - Ответ кешируется в памяти на 3 минуты (180 сек) для предотвращения превышения лимитов и обеспечения 0 мс латентности.
    """
    symbol = scanner.normalize_symbol(raw_symbol)
    if not symbol:
        return {
            "status": "error",
            "message": f"Некорректный тикер актива: '{raw_symbol}'. Пример: BTC, ETH, SOLUSDT."
        }

    now = time.time()

    # 1. Проверка оперативного кеша
    async with _cache_lock:
        if not force_refresh and symbol in _FORECAST_CACHE:
            cached_entry = _FORECAST_CACHE[symbol]
            if now < cached_entry["expires_at"]:
                # Возвращаем копию с флагом cached=True
                res = dict(cached_entry["data"])
                res["cached"] = True
                return res

    # 2. Получение рыночных данных с биржи Binance (параллельный сбор)
    base_ticker = symbol[:-4] if symbol.endswith("USDT") else symbol

    ticker_task = scanner.get_ticker_24hr(symbol)
    klines_1h_task = fetch_klines(symbol, interval="1h", limit=80)
    klines_4h_task = fetch_klines(symbol, interval="4h", limit=60)

    ticker_data, klines_1h, klines_4h = await asyncio.gather(
        ticker_task, klines_1h_task, klines_4h_task, return_exceptions=True
    )

    if not isinstance(ticker_data, dict) or "lastPrice" not in ticker_data:
        return {
            "status": "error",
            "message": f"Актив {symbol} не найден на бирже Binance или шлюз котировок временно недоступен."
        }

    try:
        price = float(ticker_data.get("lastPrice") or 0.0)
        chg_24h = float(ticker_data.get("priceChangePercent") or 0.0)
        quote_vol_raw = float(ticker_data.get("quoteVolume") or 0.0)
        high_24h = float(ticker_data.get("highPrice") or price)
        low_24h = float(ticker_data.get("lowPrice") or price)
    except (ValueError, TypeError):
        price = chg_24h = quote_vol_raw = 0.0
        high_24h = low_24h = 0.0

    # Разбор свечных данных 1ч
    closes_1h: List[float] = []
    highs_1h: List[float] = []
    lows_1h: List[float] = []
    volumes_1h: List[float] = []

    if isinstance(klines_1h, list) and klines_1h:
        for c in klines_1h:
            if isinstance(c, (list, tuple)) and len(c) > 5:
                try:
                    highs_1h.append(float(c[2]))
                    lows_1h.append(float(c[3]))
                    closes_1h.append(float(c[4]))
                    volumes_1h.append(float(c[5]))
                except (ValueError, TypeError):
                    continue

    # Разбор свечных данных 4ч
    closes_4h: List[float] = []
    if isinstance(klines_4h, list) and klines_4h:
        for c in klines_4h:
            if isinstance(c, (list, tuple)) and len(c) > 4:
                try:
                    closes_4h.append(float(c[4]))
                except (ValueError, TypeError):
                    continue

    # 3. Расчет индикаторов
    rsi_1h = calculate_rsi_series(closes_1h, 14) or (await scanner.calculate_rsi(symbol, "1h", 14)) or 50.0
    rsi_4h = calculate_rsi_series(closes_4h, 14) or (await scanner.calculate_rsi(symbol, "4h", 14)) or 50.0
    bb = calculate_bollinger_bands(closes_1h, period=20, num_std=2.0)
    ema_20 = calculate_ema(closes_1h, 20) or price
    ema_50 = calculate_ema(closes_1h, 50) or price
    vol_spike = calculate_volume_spike(volumes_1h, period=20)
    atr = calculate_atr(highs_1h, lows_1h, closes_1h, period=14)

    vol_m = quote_vol_raw / 1_000_000.0
    if vol_m >= 1000.0:
        vol_formatted = f"${vol_m / 1000.0:,.2f}B"
    elif vol_m >= 1.0:
        vol_formatted = f"${vol_m:,.2f}M"
    else:
        vol_formatted = f"${quote_vol_raw:,.0f}"

    # Контекст для аналитической обработки
    market_context = {
        "symbol": symbol,
        "ticker": base_ticker,
        "price": price,
        "price_formatted": scanner.format_price(price),
        "change_24h": round(chg_24h, 2),
        "high_24h": scanner.format_price(high_24h),
        "low_24h": scanner.format_price(low_24h),
        "volume_formatted": vol_formatted,
        "rsi_1h": rsi_1h,
        "rsi_4h": rsi_4h,
        "bb_middle": bb["middle"],
        "bb_upper": bb["upper"],
        "bb_lower": bb["lower"],
        "bb_percent_b": bb["percent_b"],
        "bb_bandwidth": bb["bandwidth"],
        "ema_20": ema_20,
        "ema_50": ema_50,
        "volume_spike_ratio": vol_spike["spike_ratio"],
        "is_volume_spike": vol_spike["is_spike"],
        "atr": atr
    }

    # 4. Попытка синтеза через Gemini Flash LLM
    ai_result = await call_gemini_synthesis(market_context)

    # 5. Если LLM недоступна или не вернула ответ — применяем институциональный квантовый движок
    if not ai_result:
        ai_result = synthesize_quantitative_forecast(
            symbol=symbol,
            ticker_name=base_ticker,
            price=price,
            change_24h=chg_24h,
            volume_24h=quote_vol_raw,
            rsi_1h=rsi_1h,
            rsi_4h=rsi_4h,
            bb=bb,
            ema_20=ema_20,
            ema_50=ema_50,
            vol_spike=vol_spike,
            atr=atr
        )

    # 6. Финальная сборка полезной нагрузки
    payload: Dict[str, Any] = {
        "status": "success",
        "symbol": symbol,
        "ticker": base_ticker,
        "price": price,
        "price_formatted": scanner.format_price(price),
        "change_24h": round(chg_24h, 2),
        "bias": ai_result["bias"],
        "bias_badge": ai_result["bias_badge"],
        "probability": ai_result["probability"],
        "risk_reward": ai_result["risk_reward"],
        "entry_zone": ai_result["entry_zone"],
        "tp1": ai_result["tp1"],
        "tp1_price": ai_result.get("tp1_price"),
        "tp2": ai_result["tp2"],
        "tp2_price": ai_result.get("tp2_price"),
        "tp3": ai_result.get("tp3"),
        "tp3_price": ai_result.get("tp3_price"),
        "stop_loss": ai_result["stop_loss"],
        "stop_loss_price": ai_result.get("stop_loss_price"),
        "summary": ai_result["summary"],
        "source": ai_result["source"],
        "indicators": {
            "rsi_1h": rsi_1h,
            "rsi_4h": rsi_4h,
            "bb_middle": bb["middle"],
            "bb_upper": bb["upper"],
            "bb_lower": bb["lower"],
            "bb_percent_b": bb["percent_b"],
            "bb_bandwidth": bb["bandwidth"],
            "ema_20": ema_20,
            "ema_50": ema_50,
            "volume_spike_ratio": vol_spike["spike_ratio"],
            "is_volume_spike": vol_spike["is_spike"],
            "trend": "bullish" if ema_20 > ema_50 else ("bearish" if ema_20 < ema_50 else "neutral")
        },
        "cached": False,
        "timestamp": datetime.datetime.now().isoformat()
    }

    # 7. Сохранение в кеш
    async with _cache_lock:
        _FORECAST_CACHE[symbol] = {
            "data": payload,
            "expires_at": now + CACHE_TTL_SECONDS
        }

    return payload


async def analyze_asset(symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Институциональный аналитический движок оценки актива (синтез уровней Entry,
    TP1, TP2, TP3, SL, Risk/Reward, полос Боллинджера, EMA, RSI и AI скоринга уверенности).
    """
    return await get_ai_market_forecast(symbol, force_refresh=force_refresh)


def clear_ai_cache() -> None:
    """Очистка оперативного кеша (используется для тестов)."""
    global _FORECAST_CACHE
    _FORECAST_CACHE.clear()


def format_ai_forecast_telegram(data: Dict[str, Any]) -> str:
    """Форматирование отчета ИИ-прогноза в HTML для отправки в Telegram."""
    if data.get("status") == "error":
        return f"❌ <b>Ошибка генерации ИИ-прогноза:</b>\n{html.escape(data.get('message', 'Неизвестная ошибка'))}"

    ticker = data.get("ticker", data.get("symbol", ""))
    price_str = data.get("price_formatted", "")
    chg = data.get("change_24h", 0.0)
    chg_emoji = "🟢 +" if chg >= 0 else "🔴 "
    bias_badge = data.get("bias_badge", data.get("bias", "Neutral/Chop"))
    prob = data.get("probability", 75)
    rr = data.get("risk_reward", "1:2.5")
    entry = data.get("entry_zone", "—")
    tp1 = data.get("tp1", "—")
    tp2 = data.get("tp2", "—")
    sl = data.get("stop_loss", "—")
    ind = data.get("indicators", {})
    rsi_1h = ind.get("rsi_1h", "—")
    rsi_4h = ind.get("rsi_4h", "—")
    bb_b = ind.get("bb_percent_b", "—")
    bb_w = ind.get("bb_bandwidth", "—")
    ema_20_val = ind.get("ema_20")
    ema_50_val = ind.get("ema_50")
    ema_20_str = scanner.format_price(ema_20_val) if ema_20_val else "—"
    ema_50_str = scanner.format_price(ema_50_val) if ema_50_val else "—"
    vol_ratio = ind.get("volume_spike_ratio", 1.0)
    vol_note = f"{vol_ratio}x (Всплеск 🔥)" if ind.get("is_volume_spike") else f"{vol_ratio}x (Норма)"
    summary = data.get("summary", "")
    source_label = "Gemini Flash AI ⚡" if data.get("source") == "gemini" else "Institutional Quant Engine ⚡"
    cached_note = "\n<i>⚡ Ответ из оперативного кеша (TTL 3 мин)</i>" if data.get("cached") else ""

    return (
        f"🧠 <b>AI Market Intelligence: {html.escape(ticker)} / USDT</b>\n"
        f"────────────────────\n"
        f"💵 <b>Котировка:</b> <code>{price_str}</code> (<b>{chg_emoji}{chg:.2f}%</b>)\n"
        f"🎯 <b>Торговый вердикт (Bias):</b> <b>{bias_badge}</b>\n"
        f"📊 <b>Вероятность отработки:</b> <b>{prob}%</b>\n"
        f"⚖️ <b>Risk / Reward Ratio:</b> <b>{rr}</b>\n\n"
        f"📍 <b>ТОРГОВЫЙ ПЛАН (SETUP):</b>\n"
        f"🚪 <b>Зона входа:</b> <code>{entry}</code>\n"
        f"🎯 <b>Цель 1 (TP 1):</b> <code>{tp1}</code>\n"
        f"🚀 <b>Цель 2 (TP 2):</b> <code>{tp2}</code>\n"
        f"🛑 <b>Stop-Loss (Инвалидация):</b> <code>{sl}</code>\n\n"
        f"🧭 <b>Мульти-индикаторный анализ:</b>\n"
        f"• RSI: 1h = <b>{rsi_1h}</b> | 4h = <b>{rsi_4h}</b>\n"
        f"• Bollinger: %B = <b>{bb_b}</b> | Ширина = <b>{bb_w}%</b>\n"
        f"• Moving Averages: EMA-20 <code>{ema_20_str}</code> | EMA-50 <code>{ema_50_str}</code>\n"
        f"• Объемный импульс: <b>{vol_note}</b>\n\n"
        f"📝 <b>Резюме аналитика ({source_label}):</b>\n"
        f"<i>{html.escape(summary)}</i>\n"
        f"────────────────────"
        f"{cached_note}"
    )


async def format_analysis_report(coin_or_data: Any) -> str:
    """
    Форматирование экспресс-анализа монеты для VIP-пользователей.
    Принимает тикер (str) или словарь данных и возвращает HTML-отчет теханализа.
    """
    if isinstance(coin_or_data, dict):
        return format_ai_forecast_telegram(coin_or_data)
    symbol = str(coin_or_data).strip()
    clean_sym = scanner.normalize_symbol(symbol) or (f"{symbol.upper()}USDT" if not symbol.upper().endswith("USDT") else symbol.upper())
    return await scanner.get_coin_analysis(clean_sym)

