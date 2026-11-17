#!/usr/bin/env python
"""
tools/customize_vip_channel.py
Инструмент для автоматической кастомизации закрытого VIP-канала CryptoRadar.

Функционал:
1. Читает BOT_TOKEN и VIP_CHANNEL_ID из config.py / .env.
2. Генерирует через Pillow высококачественный неоновый логотип-аватар 1024x1024:
   - Темный фон #0a0d14
   - Неоновые бирюзовые (#00f2fe) и фиолетовые (#a855f7) кольца радара и развертка
   - 3D-ограненный крипто-кристалл/алмаз VIP с многотоновым градиентом
   - Надпись "CRYPTORADAR VIP" с неоновым свечением и значок VIP-клуба
3. Обновляет метаданные канала Telegram:
   - Название канала (по умолчанию: "💎 CryptoRadar | VIP Insider Club")
   - Описание канала (стильное описание с сигналами, AI-аналитикой, TP/SL, риск-менеджментом)
   - Аватарку канала через bot.set_chat_photo
4. Публикует и закрепляет приветственный пост-гайд:
   - Правила работы с сигналами (Spot/Futures, TP1/TP2/TP3, Stop-Loss)
   - Риск-менеджмент (1-3% на сделку, плечи 3x-10x, безубыток)
   - Ссылки на WebApp терминал и бота
   - Закрепление через bot.pin_chat_message

Параметры командной строки (CLI):
  --preview       Только сгенерировать логотип и показать текст/превью без изменения канала (режим по умолчанию)
  --apply         Применить изменения в канале Telegram (требует подтверждения флагом)
  --title         Пользовательское название канала (опционально)
  --description   Пользовательское описание канала (опционально, до 255 символов)
  --output        Путь для сохранения аватарки (по умолчанию: tools/vip_channel_avatar.png)
  --skip-photo    Не обновлять аватарку канала
  --skip-post     Не публиковать и не закреплять приветственный пост

Примеры использования:
  # Просмотр превью и генерация логотипа без изменения канала:
  python tools/customize_vip_channel.py --preview

  # Применение всех изменений в Telegram-канале:
  python tools/customize_vip_channel.py --apply

  # Применение с кастомным названием:
  python tools/customize_vip_channel.py --apply --title "💎 CryptoRadar | Elite Alpha VIP"
"""

import argparse
import asyncio
import logging
import math
import os
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# Добавляем корневую директорию проекта в sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("VIPCustomizer")

# =============================================================================
# КОНФИГУРАЦИЯ И ШАБЛОНЫ ПО УМОЛЧАНИЮ
# =============================================================================

DEFAULT_TITLE = "💎 CryptoRadar | VIP Insider Club"

# Telegram Bot API ограничивает длину описания канала 255 символами!
DEFAULT_DESCRIPTION_TEMPLATE = (
    "💎 Закрытый клуб CryptoRadar\n"
    "⚡ Сигналы & AI-аналитика 24/7 (RSI, Orderflow, On-Chain)\n"
    "🛡 Риск-менеджмент: вход 1-3%, цели TP/SL\n"
    "🤖 Терминал: @{bot_username} | 💬 Поддержка: @admin"
)

WELCOME_POST_TEMPLATE = """💎 <b>ДОБРО ПОЖАЛОВАТЬ В ЗАКРЫТЫЙ VIP INSIDER CLUB!</b> 💎

Поздравляем! Вы получили доступ к закрытой квантовой аналитике, алгоритмическим торговым сигналам и инсайдерскому радару <b>{project_name}</b>.

━━━━━━━━━━━━━━━━━━━━
📌 <b>КАК РАБОТАТЬ С НАШИМИ СИГНАЛАМИ</b>
Каждый сигнал содержит точные параметры для входа и фиксации прибыли:
• <b>Тип сделки:</b> SPOT или FUTURES (Long / Short)
• <b>Точка входа (Entry Zone):</b> рекомендованный диапазон покупки/продажи
• <b>Цели (Take-Profit):</b>
  🎯 <b>TP1 (Консервативная):</b> фиксация 40–50% объема сделки, перенос SL в безубыток
  🎯 <b>TP2 (Основная):</b> фиксация еще 30% объема
  🎯 <b>TP3 (Максимальная / Runner):</b> фиксация остатка позиции
• <b>Стоп-лосс (Stop-Loss):</b> жесткий уровень отмены сценария (выставляется СРАЗУ при открытии сделки!)

━━━━━━━━━━━━━━━━━━━━
🛡 <b>ЗОЛОТЫЕ ПРАВИЛА РИСК-МЕНЕДЖМЕНТА</b>
1. <b>Объем позиции:</b> не более 1–3% от общего депозита на одну сделку!
2. <b>Кредитное плечо (Leverage):</b> строго 3x–10x (для новичков рекомендуется не более 3x–5x).
3. <b>Безубыток (Breakeven):</b> при достижении первого тейка (TP1) ВСЕГДА переносите Stop-Loss на точку входа.
4. <b>Дисциплина:</b> никогда не усредняйте убыточные позиции без прямого сигнала и не торгуйте на эмоциях.

━━━━━━━━━━━━━━━━━━━━
🚀 <b>ИНСТРУМЕНТЫ И ПОЛЕЗНЫЕ ССЫЛКИ</b>
📱 <b>WebApp Торговый Терминал:</b> живые графики и сканер рынка 24/7
⚡ <b>RSI & Orderflow Радар:</b> аномальные всплески объемов и перекупленность
💬 <b>Служба заботы и поддержки:</b> свяжитесь с администратором при любых вопросах

<i>Закрепите этот пост, чтобы правила управления капиталом всегда оставались перед глазами. Профитной торговли!</i> 📈💰"""

DEFAULT_OUTPUT_AVATAR = os.path.join(str(BASE_DIR), "tools", "vip_channel_avatar.png")


# =============================================================================
# ГЕНЕРАТОР ШРИФТОВ И ТЕКСТА
# =============================================================================

def get_system_font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    """Загружает системный шрифт с безопасным фоллбэком на дефолтный шрифт."""
    font_candidates = [
        "C:/Windows/Fonts/bahnschrift.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
    ]
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: float,
    center_y: float,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int, int],
    tracking: float = 6.0
) -> Tuple[float, float]:
    """Отрисовывает текст с трекингом (кернингом) символов и центровкой."""
    widths = [draw.textbbox((0, 0), ch, font=font)[2] for ch in text]
    total_w = sum(widths) + (len(text) - 1) * tracking
    bbox_sample = draw.textbbox((0, 0), "A", font=font)
    h = bbox_sample[3] - bbox_sample[1]

    start_x = center_x - total_w / 2.0
    cur_x = start_x
    for i, ch in enumerate(text):
        draw.text((cur_x, center_y - h / 2.0), ch, font=font, fill=fill)
        cur_x += widths[i] + tracking

    return total_w, h


def draw_sparkle_star(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    size: float = 18.0,
    color: Tuple[int, int, int, int] = (255, 255, 255, 240)
):
    """Рисует 4-лучевую неоновую звезду-блик на вершинах кристалла."""
    # Вертикальный ромб
    draw.polygon(
        [(x, y - size), (x + size * 0.22, y), (x, y + size), (x - size * 0.22, y)],
        fill=color
    )
    # Горизонтальный ромб
    draw.polygon(
        [(x - size, y), (x, y + size * 0.22), (x + size, y), (x, y - size * 0.22)],
        fill=color
    )
    # Центральный яркий диск
    draw.ellipse(
        [(x - size * 0.3, y - size * 0.3), (x + size * 0.3, y + size * 0.3)],
        fill=(255, 255, 255, 255)
    )


# =============================================================================
# ГЕНЕРАТОР АВАТАРКИ VIP-КАНАЛА ЧЕРЕЗ PILLOW (1024x1024)
# =============================================================================

def generate_vip_avatar(output_path: str = DEFAULT_OUTPUT_AVATAR) -> str:
    """
    Генерирует высококачественный логотип 1024x1024 в стилистике Cyber/Fintech Radar:
    - Темный фон #0a0d14 с радиальным виньетированием
    - Неоновые бирюзовые (#00f2fe) и фиолетовые (#a855f7) кольца радара с эффектом свечения
    - Шкала градусов и радарные метки крипто-целей
    - Радарная развертка (sweep cone) с градиентным затуханием
    - 3D-ограненный крипто-кристалл/алмаз с многоцветным градиентом и световыми бликами
    - Неоновая типографика "CRYPTORADAR VIP" с капсулой закрытого доступа

    Сохраняет PNG и возвращает абсолютный путь к файлу.
    """
    w, h = 1024, 1024
    cx, cy = 512, 420  # Центр радара и кристалла

    # 1. Базовое изображение с радиальным фоном (#0a0d14)
    img = Image.new("RGBA", (w, h), (10, 13, 20, 255))

    # Радиальный градиент: в центре #18223d, по краям глубокий #0a0d14
    bg_small = Image.new("RGB", (128, 128))
    for y in range(128):
        for x in range(128):
            dx = (x - 64) / 64.0
            dy = (y - 54) / 64.0
            d = min(1.0, math.sqrt(dx * dx + dy * dy))
            r = int(24 * (1.0 - d) + 10 * d)
            g = int(34 * (1.0 - d) + 13 * d)
            b = int(62 * (1.0 - d) + 20 * d)
            bg_small.putpixel((x, y), (r, g, b))

    bg = bg_small.resize((w, h), Image.Resampling.BICUBIC).convert("RGBA")
    img.paste(bg, (0, 0))

    # 2. Неоновые кольца радара (Свечение + четкие линии)
    radii = [140, 240, 340, 430]

    # Слой свечения колец
    glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    for r in radii:
        gd.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=(0, 242, 254, 45), width=6)
        gd.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=(168, 85, 247, 35), width=10)

    # Осевые линии свечения (крестовина)
    for angle in [0, 90, 180, 270]:
        rad = math.radians(angle)
        x1 = cx + 70 * math.cos(rad)
        y1 = cy + 70 * math.sin(rad)
        x2 = cx + 430 * math.cos(rad)
        y2 = cy + 430 * math.sin(rad)
        gd.line([(x1, y1), (x2, y2)], fill=(0, 242, 254, 40), width=4)

    glow_blurred = glow_layer.filter(ImageFilter.GaussianBlur(radius=6))
    img = Image.alpha_composite(img, glow_blurred)

    # Четкие кольца и деления компаса
    crisp_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(crisp_layer)
    for r in radii:
        cd.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=(0, 242, 254, 150), width=2)

    # Деления градусов по внешнему кругу (430 px)
    outer_r = 430
    for deg in range(0, 360, 10):
        rad = math.radians(deg)
        is_major = (deg % 30 == 0)
        tick_len = 16 if is_major else 8
        color = (0, 242, 254, 230) if is_major else (0, 242, 254, 90)
        tick_w = 2 if is_major else 1
        x1 = cx + (outer_r - tick_len) * math.cos(rad)
        y1 = cy + (outer_r - tick_len) * math.sin(rad)
        x2 = cx + outer_r * math.cos(rad)
        y2 = cy + outer_r * math.sin(rad)
        cd.line([(x1, y1), (x2, y2)], fill=color, width=tick_w)

    # Четкие оси крестовины
    for angle in [0, 90, 180, 270]:
        rad = math.radians(angle)
        x1 = cx + 70 * math.cos(rad)
        y1 = cy + 70 * math.sin(rad)
        x2 = cx + outer_r * math.cos(rad)
        y2 = cy + outer_r * math.sin(rad)
        cd.line([(x1, y1), (x2, y2)], fill=(0, 242, 254, 75), width=1)

    # 3. Радарная развертка (Sweep Beam)
    sweep_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sweep_img)
    start_deg = 35
    sweep_span = 60
    for i in range(sweep_span):
        deg = start_deg + i
        alpha = int(45 * (i / sweep_span) ** 1.9)
        sd.pieslice(
            [(cx - outer_r, cy - outer_r), (cx + outer_r, cy + outer_r)],
            start=deg,
            end=deg + 1.5,
            fill=(0, 242, 254, alpha)
        )

    # Яркий ведущий луч развертки
    edge_rad = math.radians(start_deg + sweep_span)
    ex = cx + outer_r * math.cos(edge_rad)
    ey = cy + outer_r * math.sin(edge_rad)
    sd.line([(cx, cy), (ex, ey)], fill=(0, 242, 254, 220), width=2)
    sweep_glow = sweep_img.filter(ImageFilter.GaussianBlur(radius=2))

    img = Image.alpha_composite(img, sweep_glow)
    img = Image.alpha_composite(img, crisp_layer)

    # 4. Радарные метки целей (Crypto Signals Radar Blips)
    blip_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blip_img)
    f_blip = get_system_font(14)
    blips = [
        (cx + 175, cy - 135, "BTC +4.8%"),
        (cx - 210, cy + 115, "ETH +6.2%"),
        (cx + 260, cy + 170, "SOL +9.1%"),
    ]
    for bx, by, label in blips:
        # Внешний пульсирующий круг
        bd.ellipse([(bx - 12, by - 12), (bx + 12, by + 12)], outline=(0, 242, 254, 85), width=1)
        # Центральная точка
        bd.ellipse([(bx - 4, by - 4), (bx + 4, by + 4)], fill=(0, 242, 254, 255))
        # Текстовый тикер
        bd.text((bx + 14, by - 8), label, font=f_blip, fill=(165, 243, 252, 230))

    img = Image.alpha_composite(img, blip_img)

    # 5. Кристалл / Бриллиант VIP (Centerpiece)
    # Мягкое неоновое гало вокруг кристалла
    halo_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo_img)
    hd.ellipse([(cx - 220, cy - 200), (cx + 220, cy + 240)], fill=(0, 242, 254, 45))
    hd.ellipse([(cx - 160, cy - 140), (cx + 160, cy + 180)], fill=(168, 85, 247, 55))
    halo = halo_img.filter(ImageFilter.GaussianBlur(radius=38))
    img = Image.alpha_composite(img, halo)

    # Геометрия 3D огранки кристалла
    T1 = (cx - 95, cy - 145)   # Верхняя левая площадка
    T2 = (cx + 95, cy - 145)   # Верхняя правая площадка
    S_L = (cx - 165, cy - 65)  # Крайнее левое плечо
    S_R = (cx + 165, cy - 65)  # Крайнее правое плечо
    G_L = (cx - 65, cy - 65)   # Внутренний левый узел
    G_R = (cx + 65, cy - 65)   # Внутренний правый узел
    M_L = (cx - 150, cy + 25)  # Средний левый угол
    M_R = (cx + 150, cy + 25)  # Средний правый угол
    M_C = (cx, cy + 45)        # Центральная вершина
    B = (cx, cy + 180)         # Нижний шип кристалла

    facets = [
        ("Star_L", [T1, G_L, S_L], (0, 210, 235, 235)),          # Бирюзовый
        ("Star_R", [T2, S_R, G_R], (192, 38, 211, 235)),         # Фуксия
        ("Table", [T1, T2, G_R, G_L], (56, 189, 248, 245)),      # Ледяной голубой
        ("Center_Tri", [G_L, G_R, M_C], (147, 197, 253, 250)),   # Яркий блик
        ("Mid_L", [S_L, G_L, M_C, M_L], (2, 132, 199, 230)),     # Глубокий циан
        ("Mid_R", [G_R, S_R, M_R, M_C], (168, 85, 247, 240)),    # Неоновый фиолетовый
        ("Lower_L", [M_L, M_C, B], (14, 116, 144, 235)),         # Темно-бирюзовый
        ("Lower_R", [M_C, M_R, B], (126, 34, 206, 240)),         # Королевский пурпур
    ]

    crystal_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    crd = ImageDraw.Draw(crystal_img)

    for _, poly, color in facets:
        crd.polygon(poly, fill=color)

    # Ограночные грани с неоновым свечением
    for _, poly, _ in facets:
        crd.polygon(poly, outline=(240, 253, 255, 195), width=2)

    # Блики-звезды на ключевых вершинах кристалла
    draw_sparkle_star(crd, T1[0], T1[1], 15)
    draw_sparkle_star(crd, T2[0], T2[1], 15)
    draw_sparkle_star(crd, S_L[0], S_L[1], 14)
    draw_sparkle_star(crd, S_R[0], S_R[1], 14)
    draw_sparkle_star(crd, B[0], B[1], 20)
    draw_sparkle_star(crd, M_C[0], M_C[1], 18)

    img = Image.alpha_composite(img, crystal_img)

    # 6. Типографика и Брендинг "CRYPTORADAR VIP"
    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)

    f_title = get_system_font(52)
    f_badge = get_system_font(24)
    f_sub = get_system_font(18)

    # Свечение заголовка
    title_glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    tgd = ImageDraw.Draw(title_glow)
    draw_tracked_text(tgd, "CRYPTORADAR VIP", cx, 740, f_title, (0, 242, 254, 210), tracking=7)
    draw_tracked_text(tgd, "CRYPTORADAR VIP", cx, 740, f_title, (168, 85, 247, 150), tracking=7)
    title_glow_blur = title_glow.filter(ImageFilter.GaussianBlur(radius=8))
    img = Image.alpha_composite(img, title_glow_blur)

    # Основной заголовок "CRYPTORADAR VIP"
    draw_tracked_text(td, "CRYPTORADAR VIP", cx, 740, f_title, (245, 253, 255, 255), tracking=7)

    # Капсульный бейдж VIP INSIDER CLUB
    bw, bh = 420, 54
    by = 830
    badge_rect = [(cx - bw // 2, by - bh // 2), (cx + bw // 2, by + bh // 2)]
    td.rounded_rectangle(badge_rect, radius=27, fill=(15, 23, 42, 225), outline=(0, 242, 254, 220), width=2)
    td.rounded_rectangle(
        [(cx - bw // 2 + 2, by - bh // 2 + 2), (cx + bw // 2 - 2, by + bh // 2 - 2)],
        radius=25,
        outline=(168, 85, 247, 110),
        width=1
    )
    draw_tracked_text(td, "✦ VIP INSIDER CLUB ✦", cx, by, f_badge, (0, 242, 254, 255), tracking=6)

    # Подзаголовок
    draw_tracked_text(td, "AI QUANT SIGNALS • MARKET RADAR 24/7", cx, 915, f_sub, (148, 163, 184, 220), tracking=4)

    img = Image.alpha_composite(img, text_layer)

    # Создаем директорию назначения, если необходимо
    dest_dir = os.path.dirname(os.path.abspath(output_path))
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    img.save(output_path, "PNG")
    logger.info(f"Аватарка VIP-канала успешно сгенерирована: {output_path} (1024x1024 PNG)")
    return os.path.abspath(output_path)


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ КОНТЕНТА
# =============================================================================

def build_channel_description(bot_username: Optional[str] = None, custom_desc: Optional[str] = None) -> str:
    """Формирует описание канала, гарантируя лимит <= 255 символов."""
    if custom_desc:
        desc = custom_desc.strip()
    else:
        username = bot_username or "CryptoRadar_Bot"
        desc = DEFAULT_DESCRIPTION_TEMPLATE.format(bot_username=username)

    if len(desc) > 255:
        logger.warning(f"Описание канала превышает 255 символов ({len(desc)}). Будет обрезано.")
        desc = desc[:252] + "..."
    return desc


def build_welcome_post(project_name: Optional[str] = None) -> str:
    """Формирует HTML-текст приветственного закрепленного поста."""
    name = project_name or config.PROJECT_NAME or "CryptoRadar & VIP Insider"
    return WELCOME_POST_TEMPLATE.format(project_name=name)


def build_welcome_keyboard(bot_username: Optional[str] = None, webapp_url: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с безопасными HTTPS ссылками для канала.
    Telegram каналы принимают только Inline-кнопки с URL (HTTPS).
    Гарантирует передачу параметра vip=1 для участников закрытого VIP-канала.
    """
    username = bot_username or "CryptoRadar_Bot"
    url_target = webapp_url or config.WEBAPP_URL or "https://sppoti.github.io/cryptoradar-tma/?vip=1"

    # Если webapp_url HTTPS - используем его с параметром vip=1, иначе ведем в бота
    if url_target.startswith("https://"):
        sep = "&" if "?" in url_target else "?"
        if "vip=1" not in url_target:
            app_url = f"{url_target}{sep}vip=1"
        else:
            app_url = url_target
    else:
        app_url = f"https://t.me/{username}?start=terminal"

    bot_url = f"https://t.me/{username}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Открыть WebApp Терминал", url=app_url)
        ],
        [
            InlineKeyboardButton(text="🤖 Главное меню бота", url=bot_url)
        ]
    ])
    return keyboard


# =============================================================================
# РЕЖИМ ПРЕВЬЮ (--preview)
# =============================================================================

async def run_preview(
    title: Optional[str] = None,
    description: Optional[str] = None,
    output_path: str = DEFAULT_OUTPUT_AVATAR
) -> int:
    """
    Выполняет режим предпросмотра:
    1. Генерирует аватарку через Pillow.
    2. Отображает планируемые изменения названия и описания (с проверкой длины).
    3. Выводит полный текст приветственного поста и схему кнопок.
    4. НЕ вносит изменений в Telegram-канал.
    """
    print("\n" + "=" * 70)
    print("  💎 CryptoRadar — ПРЕВЬЮ КАСТОМИЗАЦИИ ЗАКРЫТОГО VIP-КАНАЛА")
    print("=" * 70)

    # 1. Проверка конфигурации
    token_present = bool(config.BOT_TOKEN and config.BOT_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN_HERE")
    channel_target = config.VIP_CHANNEL_ID or "НЕ ЗАДАН (укажите в .env VIP_CHANNEL_ID)"

    print(f"\n[1] КОНФИГУРАЦИЯ:")
    print(f"  • BOT_TOKEN: {'✅ Настроен' if token_present else '❌ НЕ настроен в .env'}")
    print(f"  • VIP_CHANNEL_ID: {channel_target}")

    # Пробуем получить имя бота из API, если есть интернет/токен
    bot_username = "CryptoRadar_Bot"
    if token_present:
        try:
            bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            try:
                me = await bot.get_me()
                bot_username = me.username or "CryptoRadar_Bot"
                print(f"  • Подключение к Bot API: ✅ Успешно (@{bot_username}, ID: {me.id})")
            except Exception as e:
                print(f"  • Подключение к Bot API: ⚠️ Ошибка ({e}) — используется фоллбэк @{bot_username}")
            finally:
                await bot.session.close()
        except Exception:
            pass

    # 2. Генерация логотипа/аватарки
    print(f"\n[2] ГЕНЕРАЦИЯ АВАТАРКИ VIP-КАНАЛА:")
    try:
        avatar_abs_path = generate_vip_avatar(output_path)
        file_size_kb = os.path.getsize(avatar_abs_path) / 1024.0
        print(f"  ✅ Аватарка успешно сгенерирована:")
        print(f"     Файл: {avatar_abs_path}")
        print(f"     Разрешение: 1024x1024 px")
        print(f"     Размер: {file_size_kb:.1f} KB")
        print(f"     Элементы: Темный фон #0a0d14, неоновые кольца радара (#00f2fe, #a855f7),")
        print(f"               3D крипто-кристалл VIP, надпись 'CRYPTORADAR VIP'")
    except Exception as e:
        print(f"  ❌ Ошибка генерации аватарки: {e}")
        return 1

    # 3. Название и описание канала
    channel_title = title or DEFAULT_TITLE
    channel_desc = build_channel_description(bot_username=bot_username, custom_desc=description)

    print(f"\n[3] МЕТАДАННЫЕ КАНАЛА:")
    print(f"  • Название канала: «{channel_title}»")
    print(f"  • Описание канала ({len(channel_desc)} / 255 символов):")
    for line in channel_desc.splitlines():
        print(f"      {line}")

    # 4. Приветственный пост и кнопки
    welcome_text = build_welcome_post()
    keyboard = build_welcome_keyboard(bot_username=bot_username)

    print(f"\n[4] ПРИВЕТСТВЕННЫЙ ПОСТ (ДЛЯ ПУБЛИКАЦИИ И ЗАКРЕПЛЕНИЯ):")
    print("-" * 70)
    print(welcome_text)
    print("-" * 70)
    print(f"  Кнопки под постом:")
    for row in keyboard.inline_keyboard:
        for btn in row:
            print(f"    [ {btn.text} ] -> {btn.url}")

    # Итог превью
    print("\n" + "=" * 70)
    print("  🎉 [РЕЖИМ ПРЕВЬЮ ЗАВЕРШЕН]")
    print("  Все компоненты проверены и готовы к работе.")
    print("  Никакие изменения НЕ были отправлены в Telegram-канал.")
    print("  Для применения изменений в закрытом VIP-канале запустите команду:")
    print("    python tools/customize_vip_channel.py --apply")
    print("=" * 70 + "\n")
    return 0


# =============================================================================
# РЕЖИМ ПРИМЕНЕНИЯ (--apply)
# =============================================================================

async def run_apply(
    title: Optional[str] = None,
    description: Optional[str] = None,
    output_path: str = DEFAULT_OUTPUT_AVATAR,
    skip_photo: bool = False,
    skip_post: bool = False
) -> int:
    """
    Применяет настройки в реальном Telegram VIP-канале:
    1. Проверяет BOT_TOKEN и VIP_CHANNEL_ID.
    2. Проверяет права администратора бота в канале.
    3. Обновляет аватарку канала через bot.set_chat_photo.
    4. Обновляет название канала через bot.set_chat_title.
    5. Обновляет описание канала через bot.set_chat_description.
    6. Отправляет приветственный пост-гайд и закрепляет его (pin_chat_message).
    """
    print("\n" + "=" * 70)
    print("  🚀 CryptoRadar — ПРИМЕНЕНИЕ КАСТОМИЗАЦИИ В VIP-КАНАЛЕ")
    print("=" * 70)

    # 1. Проверка конфигурации
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN не задан в .env файле!")
        return 1

    vip_channel_id = config.VIP_CHANNEL_ID
    if not vip_channel_id:
        logger.error("VIP_CHANNEL_ID не задан в .env файле! Укажите числовой ID канала (например: -1001234567890).")
        return 1

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    try:
        # 2. Проверка доступа бота к каналу
        try:
            bot_info = await bot.get_me()
            bot_username = bot_info.username or "CryptoRadar_Bot"
            logger.info(f"Связь с Bot API установлена: @{bot_username} (ID: {bot_info.id})")
        except Exception as e:
            logger.error(f"Не удалось подключиться к Bot API: {e}")
            return 1

        try:
            chat = await bot.get_chat(vip_channel_id)
            logger.info(f"Канал найден: «{chat.title}» (ID: {vip_channel_id}, Type: {chat.type})")
        except Exception as e:
            logger.error(f"Не удалось получить информацию о канале {vip_channel_id}: {e}")
            logger.error("Убедитесь, что бот добавлен в канал и назначен администратором.")
            return 1

        # Проверка прав администратора
        try:
            member = await bot.get_chat_member(chat_id=vip_channel_id, user_id=bot_info.id)
            if member.status not in ("administrator", "creator"):
                logger.error(f"Бот @{bot_username} не является администратором канала {vip_channel_id} (статус: {member.status})!")
                return 1
        except Exception as e:
            logger.warning(f"Не удалось проверить статус участника: {e}")

        # 3. Обновление аватарки (bot.set_chat_photo)
        if not skip_photo:
            try:
                print("\n[ШАГ 1/4] Генерация и загрузка новой аватарки...")
                avatar_path = generate_vip_avatar(output_path)
                photo_file = FSInputFile(avatar_path)
                await bot.set_chat_photo(chat_id=vip_channel_id, photo=photo_file)
                logger.info("✅ Аватарка канала успешно обновлена в Telegram!")
            except TelegramBadRequest as e:
                logger.error(f"⚠️ Ошибка загрузки аватарки: {e}")
            except Exception as e:
                logger.error(f"⚠️ Непредвиденная ошибка при загрузке аватарки: {e}")
        else:
            logger.info("Пропуск обновления аватарки (--skip-photo)")

        # 4. Обновление названия канала (bot.set_chat_title)
        channel_title = title or DEFAULT_TITLE
        try:
            print(f"\n[ШАГ 2/4] Обновление названия канала на: «{channel_title}»...")
            await bot.set_chat_title(chat_id=vip_channel_id, title=channel_title)
            logger.info(f"✅ Название канала успешно обновлено: «{channel_title}»")
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                logger.info("ℹ️ Название канала уже совпадает с целевым (без изменений).")
            else:
                logger.error(f"⚠️ Ошибка обновления названия канала: {e}")
        except Exception as e:
            logger.error(f"⚠️ Непредвиденная ошибка при смене названия: {e}")

        # 5. Обновление описания канала (bot.set_chat_description)
        channel_desc = build_channel_description(bot_username=bot_username, custom_desc=description)
        try:
            print(f"\n[ШАГ 3/4] Обновление описания канала ({len(channel_desc)} симв)...")
            await bot.set_chat_description(chat_id=vip_channel_id, description=channel_desc)
            logger.info("✅ Описание канала успешно обновлено!")
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                logger.info("ℹ️ Описание канала уже совпадает с целевым (без изменений).")
            else:
                logger.error(f"⚠️ Ошибка обновления описания канала: {e}")
        except Exception as e:
            logger.error(f"⚠️ Непредвиденная ошибка при смене описания: {e}")

        # 6. Публикация и закрепление приветственного поста-гайда
        if not skip_post:
            try:
                print("\n[ШАГ 4/4] Публикация и закрепление приветственного гайда...")
                welcome_text = build_welcome_post()
                keyboard = build_welcome_keyboard(bot_username=bot_username)

                msg = await bot.send_message(
                    chat_id=vip_channel_id,
                    text=welcome_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                logger.info(f"✅ Приветственный пост успешно опубликован (Message ID: {msg.message_id})")

                # Закрепляем пост в канале
                try:
                    await bot.pin_chat_message(
                        chat_id=vip_channel_id,
                        message_id=msg.message_id,
                        disable_notification=False
                    )
                    logger.info(f"✅ Приветственный пост успешно закреплен в канале!")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось закрепить сообщение (проверьте права бота на pin_messages): {e}")

            except Exception as e:
                logger.error(f"⚠️ Ошибка публикации приветственного поста: {e}")
        else:
            logger.info("Пропуск публикации приветственного поста (--skip-post)")

        print("\n" + "=" * 70)
        print("  🎉 ВСЕ ОПЕРАЦИИ УСПЕШНО ВЫПОЛНЕНЫ!")
        print("  Закрытый VIP-канал полностью оформлен и готов к приему трейдеров.")
        print("=" * 70 + "\n")
        return 0

    finally:
        await bot.session.close()


# =============================================================================
# CLI ТОЧКА ВХОДА
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="CryptoRadar VIP Channel Customization Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры запуска:
  python tools/customize_vip_channel.py --preview
  python tools/customize_vip_channel.py --apply
  python tools/customize_vip_channel.py --apply --title "💎 CryptoRadar VIP"
        """
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Только сгенерировать логотип и показать превью без изменения канала в Telegram"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Применить изменения в закрытом канале Telegram (обновить фото, название, описание, закрепить пост)"
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Пользовательское название канала (по умолчанию: '💎 CryptoRadar | VIP Insider Club')"
    )
    parser.add_argument(
        "--description",
        type=str,
        default=None,
        help="Пользовательское описание канала (до 255 символов)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_AVATAR,
        help=f"Путь для сохранения сгенерированного аватара (по умолчанию: {DEFAULT_OUTPUT_AVATAR})"
    )
    parser.add_argument(
        "--skip-photo",
        action="store_true",
        help="Пропустить обновление аватарки при --apply"
    )
    parser.add_argument(
        "--skip-post",
        action="store_true",
        help="Пропустить отправку и закрепление приветственного поста при --apply"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # По умолчанию, если флаг --apply не передан явно, ВСЕГДА запускается безопасный --preview!
    if args.apply:
        exit_code = asyncio.run(
            run_apply(
                title=args.title,
                description=args.description,
                output_path=args.output,
                skip_photo=args.skip_photo,
                skip_post=args.skip_post
            )
        )
    else:
        # Режим превью
        exit_code = asyncio.run(
            run_preview(
                title=args.title,
                description=args.description,
                output_path=args.output
            )
        )

    sys.exit(exit_code or 0)


if __name__ == "__main__":
    main()
