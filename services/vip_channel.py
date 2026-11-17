import asyncio
import datetime
import logging
from typing import Optional, Dict, Any, Union

from aiogram import Bot
from aiogram.types import ChatJoinRequest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import config
import database as db
import keyboards as kb

logger = logging.getLogger("VIPChannel")


def is_vip_channel_configured() -> bool:
    """Проверяет, включено ли динамическое управление закрытым VIP-каналом."""
    vip_id = config.VIP_CHANNEL_ID
    if not vip_id:
        return False
    # Если равен CHANNEL_ID, работает обратная совместимость (канал для автопостинга)
    if config.CHANNEL_ID and str(vip_id) == str(config.CHANNEL_ID):
        return False
    return True


def get_vip_channel_id() -> Union[int, str, None]:
    """Возвращает ID закрытого VIP-канала или None."""
    return config.VIP_CHANNEL_ID if is_vip_channel_configured() else None


async def create_vip_invite_link(bot: Bot, user_id: int, expire_hours: int = 24) -> Optional[str]:
    """
    Генерирует персональную одноразовую пригласительную ссылку для пользователя.
    Ссылка имеет member_limit=1 и срок жизни expire_hours (по умолчанию 24 ч),
    чтобы ее нельзя было передать другим.
    При отсутствии настройки VIP_CHANNEL_ID или ошибке возвращает config.VIP_LINK.
    """
    if not is_vip_channel_configured():
        return config.VIP_LINK

    vip_channel_id = config.VIP_CHANNEL_ID
    try:
        expire_date = datetime.timedelta(hours=expire_hours)
        link_name = f"VIP_{user_id}_{int(datetime.datetime.now().timestamp())}"[:32]

        invite = await bot.create_chat_invite_link(
            chat_id=vip_channel_id,
            name=link_name,
            expire_date=expire_date,
            member_limit=1,
            creates_join_request=False
        )
        logger.info(f"Сгенерирована персональная VIP-ссылка для {user_id} в канал {vip_channel_id}")
        return invite.invite_link
    except Exception as e:
        logger.warning(f"Не удалось сгенерировать персональную ссылку в VIP-канал {vip_channel_id} для {user_id}: {e}")
        return config.VIP_LINK


async def process_join_request(event: ChatJoinRequest, bot: Bot):
    """
    Обработчик заявок на вступление (chat_join_request).
    Если у пользователя активна VIP-подписка, автоматически одобряет заявку,
    фиксирует в БД и присылает приветствие в ЛС.
    Если подписки нет — отклоняет заявку и предлагает оформить подписку.
    """
    vip_channel_id = get_vip_channel_id()
    if vip_channel_id and str(event.chat.id) != str(vip_channel_id):
        # Заявка не в VIP-канал (например, в другой чат)
        return

    user_id = event.from_user.id
    username = event.from_user.username or ""
    first_name = event.from_user.first_name or "Трейдер"

    # Гарантируем наличие пользователя в БД
    await db.get_or_create_user(user_id, username, first_name)
    has_sub = await db.is_sub_active(user_id)

    if has_sub:
        try:
            await bot.approve_chat_join_request(chat_id=event.chat.id, user_id=user_id)
            await db.record_vip_channel_join(user_id)
            logger.info(f"Заявка на вход в VIP-канал одобрена для пользователя {user_id} (@{username})")
        except Exception as e:
            logger.error(f"Ошибка одобрения заявки в VIP-канал для {user_id}: {e}")
            return

        # Приветственное сообщение в ЛС
        welcome_text = (
            f"🎉 <b>Добро пожаловать в закрытый VIP Club {config.PROJECT_NAME}!</b>\n\n"
            f"Ваша заявка на вступление в закрытый канал успешно одобрена.\n"
            f"Теперь вам доступны:\n"
            f"• 🚨 Эксклюзивные торговые сигналы и цели (TP/SL)\n"
            f"• 📈 Авторская аналитика и разборы торговых сетапов\n"
            f"• 💎 Прямой доступ к инсайдерским сводкам рынка\n\n"
            f"Удачной торговли и высокого профита! 🚀"
        )
        try:
            await bot.send_message(user_id, welcome_text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не удалось отправить приветствие в ЛС {user_id}: {e}")
    else:
        try:
            await bot.decline_chat_join_request(chat_id=event.chat.id, user_id=user_id)
            logger.info(f"Заявка на вход в VIP-канал отклонена (нет подписки) для {user_id} (@{username})")
        except Exception as e:
            logger.error(f"Ошибка отклонения заявки в VIP-канал для {user_id}: {e}")

        # Предложение оформить подписку
        decline_text = (
            f"🔒 <b>Заявка в закрытый VIP-канал отклонена</b>\n\n"
            f"Закрытый канал доступен только для участников с активной VIP-подпиской.\n\n"
            f"Чтобы получить доступ к инсайдерским сигналам, радару аномалий и закрытой аналитике, "
            f"выберите подходящий тариф ниже 👇"
        )
        try:
            await bot.send_message(
                user_id,
                decline_text,
                parse_mode="HTML",
                reply_markup=kb.get_tariffs_keyboard()
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить предложение подписки в ЛС {user_id}: {e}")


async def check_and_kick_expired_members(bot: Bot) -> int:
    """
    Проверяет пользователей, у которых истекла VIP-подписка (sub_until < now или отсутствует).
    Исключает их из VIP_CHANNEL_ID через bot.ban_chat_member + bot.unban_chat_member,
    чтобы исключить без вечного бана (пользователь сможет вступить снова после продления).
    Отправляет уведомление в ЛС с предложением продлить доступ.
    Возвращает количество исключенных пользователей.
    """
    if not is_vip_channel_configured():
        return 0

    vip_channel_id = config.VIP_CHANNEL_ID
    expired_members = await db.get_expired_vip_members()
    kicked_count = 0

    for member in expired_members:
        user_id = member["user_id"]
        # Исключаем из канала в Telegram
        try:
            # ban_chat_member + unban_chat_member исключает пользователя из закрытого канала/чата
            await bot.ban_chat_member(chat_id=vip_channel_id, user_id=user_id)
            await bot.unban_chat_member(chat_id=vip_channel_id, user_id=user_id, only_if_banned=True)
            logger.info(f"Пользователь {user_id} исключен из VIP-канала {vip_channel_id} (подписка истекла)")
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            # Пользователь уже сам покинул чат, либо бот не имеет прав, либо пользователь админ
            logger.warning(f"Не удалось исключить пользователя {user_id} из канала {vip_channel_id}: {e}")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при исключении {user_id} из канала: {e}")

        # Помечаем в БД, что участник больше не активен в канале
        await db.mark_vip_channel_left(user_id)
        kicked_count += 1

        # Уведомление в ЛС пользователю
        kick_notify = (
            f"⏳ <b>Срок действия вашей VIP-подписки истек</b>\n\n"
            f"Ваш доступ к закрытому VIP-каналу {config.PROJECT_NAME} приостановлен.\n\n"
            f"Чтобы снова получать эксклюзивные торговые сигналы, живой RSI-радар и прогнозы, "
            f"продлите подписку в меню ниже 👇"
        )
        try:
            await bot.send_message(
                user_id,
                kick_notify,
                parse_mode="HTML",
                reply_markup=kb.get_tariffs_keyboard()
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление об истечении подписки пользователю {user_id}: {e}")

    return kicked_count


async def vip_expiry_checker_loop(bot: Bot, interval_seconds: int = 1800):
    """
    Фоновый цикл периодической проверки и исключения пользователей с истекшей подпиской.
    По умолчанию проверяет каждые 30 минут (1800 сек).
    """
    logger.info(f"Запущен фоновый цикл проверки VIP-подписок (интервал: {interval_seconds} сек)...")
    while True:
        try:
            kicked = await check_and_kick_expired_members(bot)
            if kicked > 0:
                logger.info(f"Проверка VIP-подписок завершена: исключено {kicked} участников с истекшим доступом.")
        except asyncio.CancelledError:
            logger.info("Фоновый цикл проверки VIP-подписок остановлен.")
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле проверки VIP-подписок: {e}")

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Фоновый цикл проверки VIP-подписок остановлен.")
            break


async def check_bot_channel_permissions(bot: Bot) -> Dict[str, Any]:
    """
    Проверяет статус и права администратора бота в закрытом VIP-канале.
    Возвращает сводку прав и метаданных канала.
    """
    if not is_vip_channel_configured():
        return {
            "ok": False,
            "error": "VIP_CHANNEL_ID не задан или совпадает с CHANNEL_ID (активен режим статической ссылки VIP_LINK).",
            "channel_id": config.VIP_CHANNEL_ID
        }

    channel_id = config.VIP_CHANNEL_ID
    try:
        chat = await bot.get_chat(channel_id)
        bot_member = await bot.get_chat_member(chat_id=channel_id, user_id=bot.id)

        is_admin = bot_member.status in ("administrator", "creator")
        is_creator = bot_member.status == "creator"

        can_invite = is_creator or getattr(bot_member, "can_invite_users", False)
        can_restrict = is_creator or getattr(bot_member, "can_restrict_members", False)
        can_post = is_creator or getattr(bot_member, "can_post_messages", False)

        try:
            tg_members = await bot.get_chat_member_count(channel_id)
        except Exception:
            tg_members = 0

        try:
            active_db_members = len(await db.get_active_vip_channel_members())
        except Exception:
            active_db_members = 0

        return {
            "ok": True,
            "channel_id": channel_id,
            "title": chat.title or str(channel_id),
            "username": chat.username,
            "type": chat.type,
            "is_admin": is_admin,
            "can_invite_users": bool(can_invite),
            "can_restrict_members": bool(can_restrict),
            "can_post_messages": bool(can_post),
            "tg_members_count": tg_members,
            "db_members_count": active_db_members
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "channel_id": channel_id
        }
