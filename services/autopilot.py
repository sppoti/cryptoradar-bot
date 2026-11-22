import os
import asyncio
import logging
from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
import config
from services import scanner, news, vip_autopilot, canva_service, ai_analytics

logger = logging.getLogger("Autopilot")

async def publish_market_update(bot: Bot) -> bool:
    """Генерация и публикация визуальной карточки сводки рынка в канал."""
    if not config.CHANNEL_ID:
        return False
        
    try:
        btc_data = await ai_analytics.analyze_asset("BTCUSDT")
        if not btc_data or btc_data.get("status") != "success":
            return False
            
        card_path = canva_service.render_local_signal_card(btc_data)
        if not card_path or not os.path.exists(card_path):
            return False

        username = await vip_autopilot.get_bot_username(bot)
        links = vip_autopilot.build_channel_links(username, coin_symbol="BTC")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Открыть терминал", url=links["bot_terminal_url"]),
                InlineKeyboardButton(text="📊 Анализ рынка", url=links["bot_analyze_url"])
            ]
        ])

        price_fmt = btc_data.get("price_formatted") or f"${float(btc_data.get('price', 0)):,.2f}"
        caption = f"📊 <b>MARKET OVERVIEW // #BTC</b> | Price: <code>{price_fmt}</code> | Bias: <code>{btc_data.get('bias', 'Market Scan')}</code>"
        
        await bot.send_photo(
            chat_id=config.CHANNEL_ID,
            photo=FSInputFile(card_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logger.info(f"Успешно опубликована визуальная карточка сводки рынка в канал {config.CHANNEL_ID}")
        return True
    except Exception as e:
        logger.error(f"Не удалось опубликовать визуальную сводку в канал: {e}")
        return False

async def publish_flash_alert(bot: Bot) -> bool:
    """Поиск и публикация Flash-Алерта при резком пампе/дампе в виде визуальной карточки."""
    if not config.CHANNEL_ID:
        return False
        
    try:
        anomaly = await scanner.check_flash_anomaly()
        if not anomaly:
            return False

        sym = anomaly.get("symbol", "BTC")
        full_sym = f"{sym}USDT"
        asset_data = await ai_analytics.analyze_asset(full_sym)
        if not asset_data or asset_data.get("status") != "success":
            price_clean = float(str(anomaly.get("price", "0")).replace("$", "").replace(",", "") or 0.0)
            asset_data = {
                "symbol": full_sym,
                "ticker": sym,
                "price": price_clean,
                "bias": "Strong Long" if "+" in str(anomaly.get("change", "")) else "Scalp Short",
                "probability": 88,
                "risk_reward": "1:2.8",
                "indicators": {"rsi_1h": float(str(anomaly.get("rsi", "50")).replace(",", ".") or 50.0)},
                "summary": str(anomaly.get("headline", "Flash Anomaly Alert"))
            }

        card_path = canva_service.render_local_signal_card(asset_data)
        if not card_path or not os.path.exists(card_path):
            return False

        username = await vip_autopilot.get_bot_username(bot)
        links = vip_autopilot.build_channel_links(username, coin_symbol=sym)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Открыть в боте", url=links["bot_terminal_url"])]
        ])

        caption = f"⚡ <b>FLASH ALERT // #{sym}</b> | Price: <code>{anomaly['price']}</code> (<b>{anomaly['change']}</b>)"
        
        await bot.send_photo(
            chat_id=config.CHANNEL_ID,
            photo=FSInputFile(card_path),
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logger.info(f"Успешно отправлен визуальный Flash Alert по монете {sym}")
        return True
    except Exception as e:
        logger.error(f"Ошибка публикации Flash Alert: {e}")
        return False

async def autopilot_loop(bot: Bot):
    """Фоновый цикл автоматической публикации аналитики, новостей и алертов."""
    await asyncio.sleep(5)
    
    tick = 0
    while True:
        try:
            if config.CHANNEL_ID:
                # Каждые 15 минут проверяем резкие пампы/дампы (Flash Alerts)
                await publish_flash_alert(bot)
                
                # Каждые 30 минут (2 тика по 15 мин) проверяем свежие новости
                if tick % 2 == 0:
                    await news.publish_latest_news(bot)
                
                # Каждые 4 часа (16 тиков по 15 мин) публикуем сводку рынка
                if tick % 16 == 0:
                    await publish_market_update(bot)

            # ==================== ЗАКРЫТЫЙ VIP-КАНАЛ ====================
            if getattr(config, "VIP_CHANNEL_ID", None):
                # Каждые 30 минут (2 тика по 15 мин) проверяем и публикуем whale алерты
                if tick % 2 == 0:
                    await vip_autopilot.publish_vip_whale_alert(bot)

                # Каждые 4 часа (16 тиков по 15 мин) публикуем свежий VIP торговый сетап
                if tick % 16 == 0:
                    await vip_autopilot.publish_vip_trade_setup(bot)

                # Раз в сутки (96 тиков по 15 мин = 24 часа) публикуем утренний брифинг
                if tick % 96 == 0:
                    await vip_autopilot.publish_vip_morning_briefing(bot)
                    
            tick += 1
            await asyncio.sleep(900)  # 15 минут
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле автопилота: {e}")
            await asyncio.sleep(60)
