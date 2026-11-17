#!/usr/bin/env python
"""
tools/setup_vip_channel.py
Консольная утилита для проверки и настройки закрытого VIP-канала в CryptoRadar.

Запуск:
    python tools/setup_vip_channel.py
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
import database as db
from services import vip_channel


def print_header(title: str):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65 + "\n")


def print_step(num: int, title: str):
    print(f"\n--- [ШАГ {num}] {title} ---")


def print_manual_instructions():
    print_header("ИНСТРУКЦИЯ: КАК СОЗДАТЬ И НАСТРОИТЬ ЗАКРЫТЫЙ VIP-КАНАЛ")
    print("""
1️⃣ СОЗДАНИЕ КАНАЛА В TELEGRAM:
   1. Откройте приложение Telegram (на телефоне или компьютере).
   2. Нажмите на иконку создания сообщения -> «Создать канал» (New Channel).
   3. Назовите канал, например: «CryptoRadar | Закрытый VIP Club».
   4. Тип канала: обязательно выберите «Частный» (Private Channel).

2️⃣ ДОБАВЛЕНИЕ БОТА В АДМИНИСТРАТОРЫ:
   1. Зайдите в созданный канал -> «Настройки» (или клик по шапке канала).
   2. Перейдите в раздел «Администраторы» -> «Добавить администратора».
   3. Найдите вашего бота по его @username.
   4. Включите следующие права:
      [x] Пригласительные ссылки / Добавление подписчиков (can_invite_users)
      [x] Блокировка / Удаление участников (can_restrict_members)
      [x] Публикация сообщений (can_post_messages)
   5. Сохраните изменения.

3️⃣ КАК УЗНАТЬ ЧИСЛОВОЙ ID ЗАКРЫТОГО КАНАЛА:
   Способ А:
     - Опубликуйте любое тестовое сообщение в вашем канале.
     - Перешлите (Forward) это сообщение боту @userinfobot или @JsonDumpBot.
     - Бот пришлет ID канала, например: -1001987654321.
   Способ Б:
     - Откройте web.telegram.org (версию A или K).
     - Зайдите в ваш канал. В адресной строке браузера будет URL вида:
       https://web.telegram.org/a/#-1001987654321
       Ваш ID канала: -1001987654321.

4️⃣ ПРОПИСАТЬ ID В ФАЙЛЕ .env:
   Откройте файл .env в папке проекта и пропишите ID:
   VIP_CHANNEL_ID=-1001987654321

После этого запустите эту утилиту повторно:
   python tools/setup_vip_channel.py
""")


async def run_diagnostics():
    print_header("CryptoRadar — Диагностика закрытого VIP-канала")

    # Инициализация базы данных
    await db.init_db()

    # 1. Проверка BOT_TOKEN
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ ОШИБКА: BOT_TOKEN не задан в .env файле!")
        print("Пожалуйста, создайте бота через @BotFather и укажите токен в .env.")
        return 1

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    try:
        # Проверка связи с Telegram Bot API
        try:
            bot_info = await bot.get_me()
            print(f"✅ Связь с Telegram Bot API установлена.")
            print(f"   Бот: @{bot_info.username} (ID: {bot_info.id}, Имя: {bot_info.first_name})")
        except Exception as e:
            print(f"❌ Ошибка подключения бота к Telegram: {e}")
            return 1

        # 2. Проверка переменной VIP_CHANNEL_ID
        print_step(1, "Проверка переменной окружения VIP_CHANNEL_ID")
        if not config.VIP_CHANNEL_ID:
            print("⚠️ VIP_CHANNEL_ID не задан в .env!")
            print("   Сейчас бот работает в режиме обратной совместимости (статическая ссылка VIP_LINK).")
            print_manual_instructions()
            return 0

        vip_id = config.VIP_CHANNEL_ID
        print(f"ℹ️ Указан VIP_CHANNEL_ID = {vip_id}")

        if config.CHANNEL_ID and str(vip_id) == str(config.CHANNEL_ID):
            print("⚠️ ВНИМАНИЕ: VIP_CHANNEL_ID совпадает с CHANNEL_ID!")
            print("   CHANNEL_ID предназначен для автопостинга сводок.")
            print("   Для динамического управления VIP-доступом создайте отдельный закрытый канал.")
            print_manual_instructions()
            return 0

        # 3. Проверка прав бота в канале
        print_step(2, "Проверка прав бота в VIP-канале")
        diag = await vip_channel.check_bot_channel_permissions(bot)

        if not diag.get("ok"):
            print(f"❌ Не удалось получить доступ к каналу {vip_id}:")
            print(f"   Ошибка: {diag.get('error')}")
            print("\nВозможные причины:")
            print("1. Бот еще не добавлен в этот канал.")
            print("2. Бот не назначен администратором.")
            print("3. Неправильно указан ID канала (не забудьте префикс -100).")
            print_manual_instructions()
            return 1

        print(f"✅ Канал найден: «{diag['title']}» (ID: {diag['channel_id']})")
        print(f"   Участников в Telegram: {diag['tg_members_count']}")
        print(f"   Участников в базе бота: {diag['db_members_count']}")

        # Проверка прав администратора
        print("\nПроверка прав администратора:")
        has_errors = False

        if diag["is_admin"]:
            print("  ✅ Статус администратора: ДА")
        else:
            print("  ❌ Статус администратора: НЕТ (Бот не является администратором!)")
            has_errors = True

        if diag["can_invite_users"]:
            print("  ✅ Право на создание ссылок (can_invite_users): ДА")
        else:
            print("  ❌ Право на создание ссылок (can_invite_users): НЕТ")
            has_errors = True

        if diag["can_restrict_members"]:
            print("  ✅ Право на исключение участников (can_restrict_members): ДА")
        else:
            print("  ❌ Право на исключение участников (can_restrict_members): НЕТ")
            has_errors = True

        if diag["can_post_messages"]:
            print("  ✅ Право на публикацию постов (can_post_messages): ДА")
        else:
            print("  ⚠️ Право на публикацию постов (can_post_messages): НЕТ (рекомендуется включить)")

        # 4. Тестовая генерация персональной ссылки
        print_step(3, "Тестирование генерации персональной одноразовой ссылки")
        try:
            test_link = await vip_channel.create_vip_invite_link(bot, user_id=config.ADMIN_ID or 123456)
            if test_link and test_link != config.VIP_LINK:
                print(f"✅ Тестовая ссылка успешно сгенерирована:")
                print(f"   {test_link}")
                print(f"   (Действительна 24 часа, лимит входов: 1 человек)")
            else:
                print(f"⚠️ Сгенерирована ссылка-фоллбэк: {test_link}")
                has_errors = True
        except Exception as e:
            print(f"❌ Ошибка генерации тестовой ссылки: {e}")
            has_errors = True

        # Итог диагностики
        print_header("ИТОГ ДИАГНОСТИКИ")
        if not has_errors:
            print("🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО!")
            print("Бот полностью готов к динамическому управлению закрытым VIP-каналом:")
            print("  • Персональные одноразовые ссылки при оплате")
            print("  • Автоматическая обработка заявок на вступление (Join Requests)")
            print("  • Автоматическое исключение участников по истечении подписки")
            return 0
        else:
            print("⚠️ Обнаружены проблемы с правами бота в канале.")
            print("Пожалуйста, откройте настройки канала в Telegram и выдайте недостающие права.")
            return 1

    finally:
        await bot.session.close()


def main():
    try:
        exit_code = asyncio.run(run_diagnostics())
        sys.exit(exit_code or 0)
    except KeyboardInterrupt:
        print("\nДиагностика прервана.")
        sys.exit(0)


if __name__ == "__main__":
    main()
