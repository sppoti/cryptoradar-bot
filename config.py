import os
from dotenv import load_dotenv

# Загрузка переменных окружения из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# ID администратора (числовой ID в Telegram)
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

# ID закрытого VIP-канала для автопостинга (например: -1001234567890 или @my_channel)
# Если пусто, автопостинг в канал отключен, работают только функции внутри бота
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
if CHANNEL_ID.startswith("-") and CHANNEL_ID[1:].isdigit():
    CHANNEL_ID = int(CHANNEL_ID)

# ID закрытого VIP-канала для динамического управления участниками (например: -1001234567890)
# Если задан и не равен CHANNEL_ID, бот динамически выдает одноразовые ссылки и исключает неактивных подписчиков.
# Если не задан или равен CHANNEL_ID, используется обратная совместимость со статической ссылкой VIP_LINK.
VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "").strip()
if VIP_CHANNEL_ID.startswith("-") and VIP_CHANNEL_ID[1:].isdigit():
    VIP_CHANNEL_ID = int(VIP_CHANNEL_ID)
elif VIP_CHANNEL_ID.isdigit():
    VIP_CHANNEL_ID = int(VIP_CHANNEL_ID)

# Интервал автопостинга аналитики в канал (в часах)
AUTOPILOT_INTERVAL_HOURS = int(os.getenv("AUTOPILOT_INTERVAL_HOURS", "4"))

# Название проекта / VIP-клуба
PROJECT_NAME = os.getenv("PROJECT_NAME", "CryptoRadar & VIP Insider")

# Ссылка на закрытый канал/чат или контент, выдаваемый после оплаты
VIP_LINK = os.getenv("VIP_LINK", "https://t.me/+example_invite_link")

# Тарифы подписки в Telegram Stars (1 Star ≈ $0.02)
TARIFFS = {
    "sub_1m": {
        "title": "VIP доступ (1 месяц)",
        "stars": 150,  # Количество Telegram Stars
        "rub_price": 150,  # Цена в рублях при прямой оплате
        "days": 30,
        "description": "Полный доступ к сигналам, автосканеру рынка и базе знаний на 30 дней."
    },
    "sub_3m": {
        "title": "VIP доступ (3 месяца)",
        "stars": 350,
        "rub_price": 1200,
        "days": 90,
        "description": "Доступ на 90 дней со скидкой 20% + личный чат участников."
    },
    "sub_life": {
        "title": "VIP Навсегда (Lifetime)",
        "stars": 990,
        "rub_price": 3500,
        "days": 3650,  # 10 лет
        "description": "Бессрочный доступ ко всем сигналам, сканерам и обновлениям."
    }
}

# Реквизиты для прямой оплаты (СБП / Карта / Крипта)
MANUAL_PAYMENT_DETAILS = os.getenv(
    "MANUAL_PAYMENT_DETAILS",
    "💳 Перевод по СБП / Карте:\nБанк: Т-Банк / Сбер\nНомер карты: 2202208867846645\nНомер телефона (СБП): +79055356182\nПолучатель: Захар Воробей (Захар В.)"
).replace("\\n", "\n")

# WebApp и Web API конфигурация
WEBAPP_URL = os.getenv("WEBAPP_URL", "http://127.0.0.1:8080").strip()
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0").strip()
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
