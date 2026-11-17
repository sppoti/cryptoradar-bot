import asyncio
import html
import logging
from typing import Dict, Any, List, Optional
import aiohttp
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database as db
from services import scanner, ai_analytics

logger = logging.getLogger("VIPAutopilot")

ALTERNATIVE_ME_FNG_URL = "https://api.alternative.me/fng/?limit=1"

VIP_CANDIDATE_SYMBOLS = [
    "BTC", "ETH", "SOL", "NEAR", "BNB", "DOGE", "AVAX", "LINK", "SUI", "PEPE"
]

FNG_CLASSIFICATIONS_RU = {
    "Extreme Fear": "Экстремальный страх",
    "Fear": "Страх",
    "Neutral": "Нейтрально",
    "Greed": "Жадность",
    "Extreme Greed": "Экстремальная жадность"
}


def _get_fng_bar(value: int) -> str:
    """Генерация визуальной шкалы индикатора страха и жадности."""
    clamped = max(0, min(100, value))
    filled = clamped // 10
    empty = 10 - filled
    return f"[{'█' * filled}{'░' * empty}] {clamped}%"


async def get_bot_username(bot: Bot) -> str:
    """Безопасное получение username бота для формирования ссылок."""
    try:
        me = await bot.get_me()
        if me and me.username:
            return me.username
    except Exception as e:
        logger.debug(f"Не удалось получить username бота: {e}")
    return "CryptoRadar_Bot"


def build_channel_links(username: str, coin_symbol: Optional[str] = None) -> Dict[str, str]:
    """
    Формирование HTTPS URL ссылок для кнопок в Telegram-каналах.
    (Telegram запрещает кнопки с callback_data в каналах).
    Гарантированно передает vip=1 в WebApp для подписчиков VIP-канала.
    """
    base_webapp = (config.WEBAPP_URL or "").strip()
    sep = "&" if "?" in base_webapp else "?"
    symbol_part = f"&symbol={coin_symbol}" if coin_symbol else ""
    direct_vip_url = f"{base_webapp}{sep}vip=1{symbol_part}"
    bot_terminal_url = (
        f"https://t.me/{username}?start=terminal_{coin_symbol}"
        if coin_symbol
        else f"https://t.me/{username}?start=terminal"
    )
    bot_analyze_url = (
        f"https://t.me/{username}?start=analyze_{coin_symbol}"
        if coin_symbol
        else f"https://t.me/{username}?start=analyze"
    )
    bot_menu_url = f"https://t.me/{username}?start=menu"

    return {
        "webapp": direct_vip_url,
        "direct_vip_url": direct_vip_url,
        "bot_terminal_url": bot_terminal_url,
        "terminal": bot_terminal_url,
        "menu": bot_menu_url,
        "analyze": bot_analyze_url,
        "bot_analyze_url": bot_analyze_url
    }


# =============================================================================
# 1. ИНДЕКС СТРАХА И ЖАДНОСТИ (FNG)
# =============================================================================

async def get_fear_and_greed() -> Dict[str, Any]:
    """
    Асинхронный запрос к https://api.alternative.me/fng/?limit=1 (таймаут 5 сек).
    При сбое или недоступности API — расчетный институциональный фоллбэк
    на основе средней 24ч динамики котировок Binance.
    Возвращает словарь вида: {"value": "74", "classification": "Greed"}.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=5.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(ALTERNATIVE_ME_FNG_URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list) and data["data"]:
                        item = data["data"][0]
                        val_str = str(item.get("value", "50"))
                        cls_str = str(item.get("value_classification", "Neutral"))
                        logger.info(f"F&G получен из Alternative.me: {val_str} ({cls_str})")
                        return {
                            "value": val_str,
                            "classification": cls_str
                        }
    except Exception as e:
        logger.warning(f"Ошибка запроса к Alternative.me API ({e}). Переход на расчетный фоллбэк Binance.")

    # --- РАСЧЕТНЫЙ ФОЛЛБЭК НА ОСНОВЕ ДИНАМИКИ BINANCE ---
    try:
        tickers = await scanner.get_top_market_tickers(limit=10)
        if not tickers:
            # Резервный опрос основных TOP_SYMBOLS
            tasks = [scanner.get_ticker_24hr(sym) for sym, _, _ in scanner.TOP_SYMBOLS[:5]]
            res = await asyncio.gather(*tasks, return_exceptions=True)
            tickers = [t for t in res if isinstance(t, dict)]

        changes: List[float] = []
        for t in tickers:
            try:
                chg = float(t.get("priceChangePercent", 0.0))
                changes.append(chg)
            except (ValueError, TypeError):
                continue

        avg_chg = (sum(changes) / len(changes)) if changes else 0.0

        # Базовый уровень 50 (нейтрально) + взвешенный сдвиг от средней динамики рынка
        est_val = int(50.0 + (avg_chg * 4.2))
        est_val = max(12, min(88, est_val))

        if est_val >= 75:
            classification = "Extreme Greed"
        elif est_val >= 55:
            classification = "Greed"
        elif est_val >= 45:
            classification = "Neutral"
        elif est_val >= 25:
            classification = "Fear"
        else:
            classification = "Extreme Fear"

        logger.info(f"F&G рассчитан по Binance fallback: {est_val} ({classification}, avg_chg: {avg_chg:+.2f}%)")
        return {
            "value": str(est_val),
            "classification": classification
        }
    except Exception as fallback_err:
        logger.error(f"Критическая ошибка fallback F&G: {fallback_err}")
        return {
            "value": "50",
            "classification": "Neutral"
        }


# =============================================================================
# 2. УТРЕННИЙ БРИФИНГ ДЛЯ VIP-КАНАЛА
# =============================================================================

async def publish_vip_morning_briefing(bot: Bot) -> bool:
    """
    Публикует в закрытый VIP-канал (config.VIP_CHANNEL_ID)
    профессиональный утренний брифинг и торговый роадмап.
    """
    channel_id = config.VIP_CHANNEL_ID
    if not channel_id:
        logger.warning("VIP_CHANNEL_ID не задан. Публикация VIP Morning Briefing отменена.")
        return False

    try:
        # 1. Сбор F&G
        fng = await get_fear_and_greed()
        try:
            fng_int = int(fng.get("value", "50"))
        except (ValueError, TypeError):
            fng_int = 50
        fng_class_en = fng.get("classification", "Neutral")
        fng_class_ru = FNG_CLASSIFICATIONS_RU.get(fng_class_en, fng_class_en)
        fng_bar = _get_fng_bar(fng_int)

        if fng_int >= 75:
            fng_verdict = "Рынок перегрет, крайняя эйфория. Рекомендуется частичная фиксация и осторожность с лонгами."
        elif fng_int >= 55:
            fng_verdict = "Уверенное преобладание покупателей. Благоприятно для трендовых сетапов и продолжения движения."
        elif fng_int >= 45:
            fng_verdict = "Рынок в балансе. Равновесие сил, работа строго от локальных уровней поддержки и сопротивления."
        elif fng_int >= 25:
            fng_verdict = "Умеренный страх. Возрастает интерес к накоплению на локальных проливах."
        else:
            fng_verdict = "Паническая распродажа / капитуляция. Зона поиска разворотных точек и институционального набора."

        # 2. Аналитика BTC и ETH
        btc_task = ai_analytics.analyze_asset("BTCUSDT")
        eth_task = ai_analytics.analyze_asset("ETHUSDT")
        top_tickers_task = scanner.get_top_market_tickers(limit=8)

        btc_res, eth_res, top_tickers = await asyncio.gather(
            btc_task, eth_task, top_tickers_task, return_exceptions=True
        )

        # BTC данные
        if isinstance(btc_res, dict) and btc_res.get("status") == "success":
            btc_price = btc_res.get("price_formatted", "$0")
            btc_chg = btc_res.get("change_24h", 0.0)
            btc_ind = btc_res.get("indicators", {})
            btc_sup = scanner.format_price(btc_ind.get("bb_lower", 0.0) or btc_ind.get("ema_50", 0.0))
            btc_res_lvl = scanner.format_price(btc_ind.get("bb_upper", 0.0) or btc_ind.get("ema_20", 0.0))
        else:
            btc_price, btc_chg, btc_sup, btc_res_lvl = "$90,000", 0.0, "$88,500", "$92,000"

        # ETH данные
        if isinstance(eth_res, dict) and eth_res.get("status") == "success":
            eth_price = eth_res.get("price_formatted", "$0")
            eth_chg = eth_res.get("change_24h", 0.0)
            eth_ind = eth_res.get("indicators", {})
            eth_sup = scanner.format_price(eth_ind.get("bb_lower", 0.0) or eth_ind.get("ema_50", 0.0))
            eth_res_lvl = scanner.format_price(eth_ind.get("bb_upper", 0.0) or eth_ind.get("ema_20", 0.0))
        else:
            eth_price, eth_chg, eth_sup, eth_res_lvl = "$3,100", 0.0, "$2,980", "$3,250"

        # 3. Топ активы дня
        top_lines: List[str] = []
        if isinstance(top_tickers, list) and top_tickers:
            # Сортируем по абсолютному изменению за 24ч
            sorted_movers = sorted(
                top_tickers,
                key=lambda x: abs(float(x.get("priceChangePercent", 0.0) or 0.0)),
                reverse=True
            )[:4]

            for item in sorted_movers:
                sym_raw = item.get("symbol", "")
                base = sym_raw[:-4] if sym_raw.endswith("USDT") else sym_raw
                p_val = float(item.get("lastPrice", 0.0))
                c_val = float(item.get("priceChangePercent", 0.0))
                q_vol = float(item.get("quoteVolume", 0.0)) / 1_000_000.0
                sign = "🟢 +" if c_val >= 0 else "🔴 "
                top_lines.append(
                    f"• <b>#{base}</b>: <code>{scanner.format_price(p_val)}</code> "
                    f"(<b>{sign}{c_val:.2f}%</b>) | Объем: <code>${q_vol:.1f}M</code>"
                )

        if not top_lines:
            top_lines = [
                "• <b>#SOL</b>: <code>$210.50</code> (<b>🟢 +4.20%</b>) | Объем: <code>$950M</code>",
                "• <b>#NEAR</b>: <code>$6.45</code> (<b>🟢 +5.10%</b>) | Объем: <code>$320M</code>"
            ]

        top_assets_text = "\n".join(top_lines)

        # 4. Аналитический вывод и торговый план
        roadmap_text = (
            "1. <b>Фокус на тренде:</b> Удержание позиций по мажорам (BTC/ETH) выше средних скользящих EMA-50.\n"
            "2. <b>Альткоины:</b> Локальные импульсы отрабатывать строго по квантовым сетапам с фиксацией 40% на TP1.\n"
            "3. <b>Риск-менеджмент:</b> Риск на сделку 1-2%, при первом тейке — обязательный перенос Stop-Loss в безубыток."
        )

        # 5. Сборка HTML поста
        post_text = (
            "🌅 <b>VIP MORNING BRIEFING & ROADMAP</b>\n"
            "────────────────────\n"
            "🧭 <b>Индекс страха и жадности (Crypto F&G):</b>\n"
            f"• Значение: <b>{fng_int}/100</b> (<b>{fng_class_ru} / {fng_class_en}</b>)\n"
            f"• Шкала: <code>{fng_bar}</code>\n"
            f"• Вердикт: <i>{fng_verdict}</i>\n\n"
            "👑 <b>МАКРО-АКТИВЫ (БАЗОВЫЕ УРОВНИ):</b>\n"
            f"• <b>Bitcoin (BTC):</b> <code>{btc_price}</code> (<b>{btc_chg:+.2f}%</b>)\n"
            f"  ↳ <i>Поддержка:</i> <code>{btc_sup}</code> | <i>Сопротивление:</i> <code>{btc_res_lvl}</code>\n"
            f"• <b>Ethereum (ETH):</b> <code>{eth_price}</code> (<b>{eth_chg:+.2f}%</b>)\n"
            f"  ↳ <i>Поддержка:</i> <code>{eth_sup}</code> | <i>Сопротивление:</i> <code>{eth_res_lvl}</code>\n\n"
            "🔥 <b>ТОП-АКТИВЫ ДНЯ ПО ДИНАМИКЕ И ОБЪЕМУ:</b>\n"
            f"{top_assets_text}\n\n"
            "📌 <b>АНАЛИТИЧЕСКИЙ ВЫВОД И ПЛАН РАБОТЫ:</b>\n"
            f"{roadmap_text}\n"
            "────────────────────\n"
            f"💎 <i>{config.PROJECT_NAME} • Закрытый аналитический клуб</i>"
        )

        # Кнопки
        username = await get_bot_username(bot)
        links = build_channel_links(username)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Открыть WebApp (VIP)", url=links["direct_vip_url"])],
            [InlineKeyboardButton(text="🤖 Открыть в боте", url=links["bot_terminal_url"])]
        ])

        await bot.send_message(
            chat_id=channel_id,
            text=post_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logger.info(f"Успешно опубликован VIP Morning Briefing в закрытый канал {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при публикации VIP Morning Briefing: {e}")
        return False


# =============================================================================
# 3. ТОРГОВЫЙ VIP СЕТАП (TRADE SETUP)
# =============================================================================

async def publish_vip_trade_setup(bot: Bot, symbol: Optional[str] = None) -> bool:
    """
    Выбирает наиболее перспективный актив или использует переданный symbol,
    проводит квантовый анализ через ai_analytics.analyze_asset() и публикует
    детальный VIP торговый сетап в закрытый VIP-канал.
    """
    channel_id = config.VIP_CHANNEL_ID
    if not channel_id:
        logger.warning("VIP_CHANNEL_ID не задан. Публикация VIP Trade Setup отменена.")
        return False

    try:
        best_data: Optional[Dict[str, Any]] = None

        if symbol:
            best_data = await ai_analytics.analyze_asset(symbol)
        else:
            # Сканируем кандидатов и выбираем монету с наивысшим скорингом и четким сигналом
            candidates = list(VIP_CANDIDATE_SYMBOLS)
            tasks = [ai_analytics.analyze_asset(sym) for sym in candidates]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            scored_candidates = []
            for item in results:
                if not isinstance(item, dict) or item.get("status") != "success":
                    continue
                bias = item.get("bias", "")
                prob = int(item.get("probability", 70))
                # Отдаем приоритет направленным сделкам (Long / Short) перед нейтральным боковиком
                direction_weight = 10 if "Long" in bias or "Short" in bias else 0
                score = prob + direction_weight
                scored_candidates.append((score, item))

            if scored_candidates:
                scored_candidates.sort(key=lambda x: x[0], reverse=True)
                best_data = scored_candidates[0][1]

        if not best_data or best_data.get("status") != "success":
            logger.warning("Не удалось сформировать VIP Trade Setup: нет данных анализа.")
            return False

        coin_ticker = best_data.get("ticker", "BTC")
        bias = best_data.get("bias", "Scalp Long")
        is_long = "Long" in bias or bias == "Strong Long"
        trade_type = "🟢 LONG" if is_long else "🔴 SHORT"

        entry_zone = best_data.get("entry_zone", "—")
        sl_str = best_data.get("stop_loss", "—")
        tp1_str = best_data.get("tp1", "—")
        tp2_str = best_data.get("tp2", "—")
        tp3_str = best_data.get("tp3")

        # Если tp3 отсутствует, формируем математический runner уровень
        if not tp3_str:
            price_val = float(best_data.get("price", 0.0) or 1.0)
            tp2_price = float(best_data.get("tp2_price", 0.0) or price_val)
            if is_long:
                tp3_calc = tp2_price * 1.035
            else:
                tp3_calc = tp2_price * 0.965
            tp3_pct = ((tp3_calc - price_val) / price_val) * 100.0
            tp3_sign = "+" if tp3_pct >= 0 else ""
            tp3_str = f"{scanner.format_price(tp3_calc)} ({tp3_sign}{tp3_pct:.2f}%)"

        ind = best_data.get("indicators", {})
        rsi_1h = ind.get("rsi_1h", "—")
        bb_w = ind.get("bb_bandwidth", "—")
        trend = ind.get("trend", "bullish")
        trend_ru = "Восходящий 🟢" if trend == "bullish" else ("Нисходящий 🔴" if trend == "bearish" else "Боковой ⚪")
        vol_ratio = ind.get("volume_spike_ratio", 1.0)
        vol_badge = "🔥 Всплеск!" if ind.get("is_volume_spike") else "стандарт"
        prob = best_data.get("probability", 82)
        risk_reward = best_data.get("risk_reward", "1:2.8")

        post_text = (
            f"🎯 <b>VIP TRADE SETUP | #{coin_ticker}/USDT</b>\n"
            f"────────────────────\n"
            f"📈 <b>Тип сделки:</b> <b>{trade_type}</b>\n"
            f"⚙️ <b>Режим:</b> Рекомендованное плечо <b>3x-5x</b> (макс 10x) | Риск <b>1-2%</b>\n"
            f"⚖️ <b>Risk / Reward:</b> <code>{risk_reward}</code>\n\n"
            f"📍 <b>Зона входа:</b> <code>{entry_zone}</code>\n"
            f"⛔️ <b>Стоп-лосс:</b> <code>{sl_str}</code>\n\n"
            f"🎯 <b>Цели Take-Profit:</b>\n"
            f"  🎯 <b>TP1:</b> <code>{tp1_str}</code> ➔ <i>40% объема и стоп в безубыток!</i>\n"
            f"  🎯 <b>TP2:</b> <code>{tp2_str}</code> ➔ <i>30% объема</i>\n"
            f"  🚀 <b>TP3:</b> <code>{tp3_str}</code> ➔ <i>свободный остаток (Runner)</i>\n\n"
            f"📊 <b>Квантовое обоснование:</b>\n"
            f"• Индикатор RSI (1h): <b>{rsi_1h}</b>\n"
            f"• Полосы Боллинджера: ширина <b>{bb_w}%</b>\n"
            f"• EMA структура: <b>{trend_ru}</b>\n"
            f"• Объемный импульс: <b>{vol_ratio}x</b> ({vol_badge})\n"
            f"🧠 <b>Индекс уверенности модели:</b> <b>{prob}%</b>\n"
            f"────────────────────\n"
            f"🛡 <i>Внимание: Строго соблюдайте мани-менеджмент. При достижении TP1 переводите стоп-лосс в безубыток!</i>"
        )

        username = await get_bot_username(bot)
        links = build_channel_links(username, coin_symbol=coin_ticker)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Открыть WebApp (VIP)", url=links["direct_vip_url"]),
                InlineKeyboardButton(text="🤖 Открыть в боте", url=links["bot_terminal_url"])
            ]
        ])

        await bot.send_message(
            chat_id=channel_id,
            text=post_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logger.info(f"Успешно опубликован VIP Trade Setup (#{coin_ticker}) в закрытый канал {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка публикации VIP Trade Setup: {e}")
        return False


# =============================================================================
# 4. WHALE ALERT (ORDERFLOW & АНОМАЛИИ ОБЪЕМОВ)
# =============================================================================

async def publish_vip_whale_alert(bot: Bot, force: bool = False) -> bool:
    """
    Сканирует рынок на предмет экстремальных аномалий объема торгов (Volume Spike >= 1.7x)
    или резкого выноса осциллятора (RSI < 28 или > 72).
    При обнаружении публикует эксклюзивный алерт в config.VIP_CHANNEL_ID.
    Параметр force=True позволяет опубликовать алерт в тестовом режиме.
    """
    channel_id = config.VIP_CHANNEL_ID
    if not channel_id:
        logger.warning("VIP_CHANNEL_ID не задан. Публикация Whale Alert отменена.")
        return False

    scan_symbols = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "BNBUSDT",
        "DOGEUSDT", "PEPEUSDT", "SUIUSDT", "AVAXUSDT", "LINKUSDT"
    ]

    try:
        found_anomaly: Optional[Dict[str, Any]] = None

        for sym in scan_symbols:
            base_sym = sym[:-4] if sym.endswith("USDT") else sym

            # Проверяем кулдаун, если не форсированный режим
            if not force and not await db.can_post_alert(sym, "VIP_WHALE", cooldown_hours=2):
                continue

            ticker = await scanner.get_ticker_24hr(sym)
            if not ticker:
                continue

            # Получаем свечи 1h для расчета объема и RSI
            klines = await ai_analytics.fetch_klines(sym, interval="1h", limit=30)
            if not klines or len(klines) < 15:
                continue

            volumes = []
            closes = []
            for c in klines:
                try:
                    closes.append(float(c[4]))
                    volumes.append(float(c[5]))
                except (ValueError, TypeError):
                    continue

            vol_spike_data = ai_analytics.calculate_volume_spike(volumes, period=20)
            rsi_val = ai_analytics.calculate_rsi_series(closes, period=14) or 50.0

            spike_ratio = vol_spike_data.get("spike_ratio", 1.0)
            chg_pct = float(ticker.get("priceChangePercent", 0.0) or 0.0)
            price_val = float(ticker.get("lastPrice", 0.0) or 0.0)

            is_volume_anomaly = spike_ratio >= 1.7
            is_rsi_anomaly = (rsi_val < 28.0 or rsi_val > 72.0)

            if is_volume_anomaly or is_rsi_anomaly or force:
                # Определяем характер аномалии
                if rsi_val >= 70.0 or (chg_pct > 0 and spike_ratio >= 1.7):
                    anomaly_nature = "Агрессивный спотовый/фьючерсный выкуп крупным игроком"
                    squeeze_risk = "Высокий риск Short-Squeeze"
                    squeeze_side = "шортовых"
                    action_plan = (
                        "• Не шортить против импульса кита!\n"
                        "• Ожидать локального отката к EMA-20 для входа в продолжение движения\n"
                        "• Следить за фиксацией лимитных стенок в стакане"
                    )
                else:
                    anomaly_nature = "Массированный сброс объема и давление институциональных продаж"
                    squeeze_risk = "Высокий риск Long-Squeeze"
                    squeeze_side = "лонговых"
                    action_plan = (
                        "• Воздержаться от ловли падающего ножа без подтвержденного разворотного паттерна\n"
                        "• Проверить защитные стоп-лоссы по открытым позициям\n"
                        "• Готовить лимитные ордера на подбор в ключевых зонах дневной поддержки"
                    )

                found_anomaly = {
                    "symbol": base_sym,
                    "full_symbol": sym,
                    "price_str": scanner.format_price(price_val),
                    "change_str": f"{chg_pct:+.2f}%",
                    "spike_ratio": spike_ratio,
                    "rsi": rsi_val,
                    "rsi_status": "Перекупленность" if rsi_val >= 70 else ("Перепроданность" if rsi_val <= 30 else "Активный импульс"),
                    "nature": anomaly_nature,
                    "squeeze_risk": squeeze_risk,
                    "squeeze_side": squeeze_side,
                    "action_plan": action_plan
                }
                break

        if not found_anomaly:
            logger.info("Аномалий объема и RSI на рынке в данный момент не зафиксировано.")
            return False

        # Записываем в БД для исключения повторного спама
        await db.record_alert(found_anomaly["full_symbol"], "VIP_WHALE")

        post_text = (
            "🐋 <b>WHALE ORDERFLOW & VOLUME RADAR</b>\n"
            "────────────────────\n"
            f"⚡ <b>Зафиксирована аномалия крупного капитала: #{found_anomaly['symbol']}/USDT</b>\n\n"
            f"💵 <b>Текущая цена:</b> <code>{found_anomaly['price_str']}</code> (<b>{found_anomaly['change_str']}</b>)\n"
            f"🌊 <b>Объемный всплеск:</b> <b>{found_anomaly['spike_ratio']}x</b> от среднего за 20ч\n"
            f"🧭 <b>Индикатор RSI (1h):</b> <b>{found_anomaly['rsi']}</b> ({found_anomaly['rsi_status']})\n\n"
            f"🚨 <b>Orderflow анализ:</b>\n"
            f"• {found_anomaly['nature']}\n"
            f"• <b>Риск сквиза:</b> <b>{found_anomaly['squeeze_risk']}</b> (каскадная ликвидация {found_anomaly['squeeze_side']} позиций)\n\n"
            f"🛡 <b>Инструкция для трейдеров закрытого клуба:</b>\n"
            f"{found_anomaly['action_plan']}\n"
            "────────────────────\n"
            f"💎 <i>{config.PROJECT_NAME} • Инсайдерский Orderflow сканер 24/7</i>"
        )

        username = await get_bot_username(bot)
        links = build_channel_links(username, coin_symbol=found_anomaly["symbol"])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Открыть WebApp (VIP)", url=links["direct_vip_url"]),
                InlineKeyboardButton(text="🤖 Открыть в боте", url=links["bot_terminal_url"])
            ]
        ])

        await bot.send_message(
            chat_id=channel_id,
            text=post_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logger.info(f"Успешно опубликован Whale Alert (#{found_anomaly['symbol']}) в канал {channel_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка публикации VIP Whale Alert: {e}")
        return False
