import asyncio
import logging
from aiogram import Bot
import config
from services import scanner, news, vip_autopilot

logger = logging.getLogger("Autopilot")

async def publish_market_update(bot: Bot) -> bool:
    """Генерация и публикация свежей аналитики в канал."""
    if not config.CHANNEL_ID:
        return False
        
    try:
        overview = await scanner.get_market_overview()
        radar = await scanner.get_signal_radar()
        
        post_text = (
            f"🔥 <b>VIP-СВОДКА РЫНКА ОТ {config.PROJECT_NAME.upper()}</b>\n"
            f"────────────────────\n\n"
            f"{overview}\n\n"
            f"{radar}\n\n"
            f"────────────────────\n"
            f"🤖 <i>Сгенерировано автоматически аналитическим ядром бота.</i>"
        )
        
        await bot.send_message(
            chat_id=config.CHANNEL_ID,
            text=post_text,
            parse_mode="HTML"
        )
        logger.info(f"Успешно опубликован пост в VIP-канал {config.CHANNEL_ID}")
        return True
    except Exception as e:
        logger.error(f"Не удалось опубликовать пост в канал: {e}")
        return False

async def publish_flash_alert(bot: Bot) -> bool:
    """Поиск и публикация Flash-Алерта при резком пампе/дампе."""
    if not config.CHANNEL_ID:
        return False
        
    try:
        anomaly = await scanner.check_flash_anomaly()
        if not anomaly:
            return False
            
        post_text = (
            f"⚡️ <b>FLASH ALERT: РЕЗКИЙ ИМПУЛЬС РЫНКА!</b>\n"
            f"────────────────────\n\n"
            f"{anomaly['headline']}\n\n"
            f"💵 <b>Цена:</b> <code>{anomaly['price']}</code>\n"
            f"📊 <b>Динамика:</b> <b>{anomaly['change']}</b>\n"
            f"🧭 <b>Индикатор RSI (1h):</b> <b>{anomaly['rsi']}</b>\n\n"
            f"🎯 <b>Вердикт сканера:</b>\n{anomaly['verdict']}\n\n"
            f"────────────────────\n"
            f"🔍 <i>Проверить любую монету в боте:</i> @ssddssa_bot\n"
            f"📊 <i>Канал аналитики:</i> @cryptoradar_live777"
        )
        
        await bot.send_message(
            chat_id=config.CHANNEL_ID,
            text=post_text,
            parse_mode="HTML"
        )
        logger.info(f"Успешно отправлен Flash Alert по монете {anomaly['symbol']}")
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
