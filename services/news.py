import aiohttp
import xml.etree.ElementTree as ET
import re
import html
import logging
from typing import Optional, Dict, Any, List, Union
from aiogram import Bot
from aiogram.types import BufferedInputFile

import config
import database as db

logger = logging.getLogger("NewsService")

FORKLOG_RSS = "https://forklog.com/feed"


def extract_image_url(html_str: Optional[str]) -> Optional[str]:
    """Извлечение URL изображения из HTML строки (<img src=...>) или RSS-разметки."""
    if not html_str:
        return None
    # 1. Поиск атрибута src или data-src в кавычках внутри тега <img>
    match = re.search(r'<img[^>]+(?:src|data-src)=["\'](https?://[^"\']+)["\']', html_str, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # 2. Поиск без кавычек
    match_no_quotes = re.search(r'<img[^>]+(?:src|data-src)=(https?://[^\s>]+)', html_str, re.IGNORECASE)
    if match_no_quotes:
        return match_no_quotes.group(1).strip()
    return None


def clean_html(raw_html: str) -> str:
    """Очистка текста от HTML тегов и сущностей."""
    if not raw_html:
        return ""
    # Удаляем все HTML теги (включая <img ... />, <p>, </p>, etc.)
    text = re.sub(r"<[^>]+>", " ", raw_html)
    # Декодируем HTML сущности (&nbsp;, &quot;, &#8212;, &amp;, etc.)
    text = html.unescape(text)
    # Нормализуем пробелы и пустые строки, сохраняя смысловые абзацы
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned_lines = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned_lines.append("")
                prev_empty = True
        else:
            cleaned_lines.append(line)
            prev_empty = False
    return "\n".join(cleaned_lines).strip()


def format_news_post(item: Dict[str, Any], max_len: int = 1024) -> str:
    """
    Форматирование текста новости для публикации в канал.
    Полностью исключает ссылки на сторонний источник (Forklog и т.д.),
    предотвращая появление сторонних рамок предпросмотра (Link Preview).
    Ограничивает длину текста до max_len (по умолчанию 1024 для caption фото в Telegram).
    """
    raw_title = item.get("title", "").strip()
    raw_desc = item.get("description", "").strip()

    title_safe = html.escape(raw_title, quote=False)

    header = (
        "⚡️ <b>СВЕЖИЕ НОВОСТИ КРИПТОРЫНКА</b>\n"
        "────────────────────\n\n"
        f"📰 <b>{title_safe}</b>\n\n"
    )

    footer = (
        "\n\n────────────────────\n"
        "🤖 <b>Сканер сигналов:</b> @ssddssa_bot\n"
        "📊 <b>Наш канал:</b> @cryptoradar_live777"
    )

    fixed_len = len(header) + len(footer)
    avail_desc_len = max_len - fixed_len

    desc_safe = html.escape(raw_desc, quote=False)

    if avail_desc_len <= 10:
        desc_text = "..."
    elif len(desc_safe) > avail_desc_len:
        cutoff = max(0, avail_desc_len - 3)
        truncated = desc_safe[:cutoff].rstrip()
        # Избегаем обрыва внутри незавершенной HTML-сущности (например &amp)
        truncated = re.sub(r"&[a-zA-Z0-9#]*$", "", truncated).rstrip()
        desc_text = truncated + "..."
    else:
        desc_text = desc_safe

    post_text = f"{header}{desc_text}{footer}"

    # Финальная страховка от превышения лимита
    if len(post_text) > max_len:
        overflow = len(post_text) - max_len
        if len(desc_text) > overflow + 3:
            desc_text = desc_text[:-(overflow + 3)].rstrip() + "..."
            post_text = f"{header}{desc_text}{footer}"

    return post_text


def parse_rss_xml(xml_data: str) -> List[Dict[str, Any]]:
    """Парсинг XML RSS-ленты в список словарей новостей."""
    root = ET.fromstring(xml_data)
    items = root.findall("./channel/item")

    news_list = []
    for item in items:
        title = item.find("title").text if item.find("title") is not None and item.find("title").text else ""
        raw_desc = item.find("description").text if item.find("description") is not None and item.find("description").text else ""
        link = item.find("link").text if item.find("link") is not None and item.find("link").text else ""

        # 1. Извлечение URL изображения из description
        image_url = extract_image_url(raw_desc)

        # 2. Если в description не найдено, проверяем enclosure
        if not image_url:
            enclosure = item.find("enclosure")
            if enclosure is not None:
                enc_url = enclosure.get("url")
                enc_type = enclosure.get("type", "")
                if enc_url and (not enc_type or enc_type.startswith("image/")):
                    image_url = enc_url.strip()

        # 3. Проверяем media:content / media:thumbnail / content:encoded
        if not image_url:
            for child in item:
                tag_lower = child.tag.lower()
                if tag_lower.endswith("content") or tag_lower.endswith("thumbnail"):
                    cand = child.get("url")
                    if cand and cand.startswith("http"):
                        image_url = cand.strip()
                        break
                elif tag_lower.endswith("encoded") and child.text:
                    cand = extract_image_url(child.text)
                    if cand:
                        image_url = cand
                        break

        clean_desc = clean_html(raw_desc)

        if title and link:
            news_list.append({
                "title": title.strip(),
                "description": clean_desc,
                "link": link.strip(),
                "image_url": image_url
            })
    return news_list


async def fetch_rss(feed_url: str = FORKLOG_RSS) -> Optional[List[Dict[str, Any]]]:
    """Загрузка свежих новостей из RSS-ленты."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(feed_url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    xml_data = await resp.text()
                    return parse_rss_xml(xml_data)
                else:
                    logger.error(f"Ошибка загрузки RSS: HTTP {resp.status}")
    except Exception as e:
        logger.error(f"Ошибка загрузки новостей: {e}")
    return None


async def send_news_item(bot: Bot, item: Dict[str, Any], chat_id: Optional[Union[str, int]] = None) -> bool:
    """
    Отправка одной новости в канал.
    Если есть image_url, отправляется как полноценное фото (URL, либо BufferedInputFile при ошибке).
    Если фото отправить не удалось или его нет — фоллбэк на send_message с disable_web_page_preview=True.
    """
    target_chat_id = chat_id or config.CHANNEL_ID
    if not target_chat_id:
        logger.warning("target_chat_id не настроен для отправки новости")
        return False

    post_text = format_news_post(item, max_len=1024)
    image_url = item.get("image_url")
    posted = False

    # Попытка 1: Отправка как фото по URL
    if image_url:
        try:
            await bot.send_photo(
                chat_id=target_chat_id,
                photo=image_url,
                caption=post_text,
                parse_mode="HTML"
            )
            posted = True
            logger.info(f"Опубликовано фото новости (по URL) в канал: {item['title']}")
        except Exception as e_url:
            logger.warning(f"Не удалось отправить фото по URL ({image_url}): {e_url}. Пробуем скачать байты...")
            # Попытка 2: Скачивание байтов и отправка через BufferedInputFile
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as img_resp:
                        if img_resp.status == 200:
                            img_bytes = await img_resp.read()
                            filename = "news.jpg"
                            if ".webp" in image_url.lower():
                                filename = "news.webp"
                            elif ".png" in image_url.lower():
                                filename = "news.png"
                            photo_file = BufferedInputFile(img_bytes, filename=filename)
                            await bot.send_photo(
                                chat_id=target_chat_id,
                                photo=photo_file,
                                caption=post_text,
                                parse_mode="HTML"
                            )
                            posted = True
                            logger.info(f"Опубликовано фото новости (через BufferedInputFile) в канал: {item['title']}")
                        else:
                            logger.warning(f"Не удалось скачать картинку {image_url}: HTTP {img_resp.status}")
            except Exception as e_buf:
                logger.warning(f"Ошибка при скачивании/отправке BufferedInputFile: {e_buf}")

    # Попытка 3 (Фоллбэк): Если картинки нет или отправка фото не удалась
    if not posted:
        try:
            await bot.send_message(
                chat_id=target_chat_id,
                text=post_text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            posted = True
            logger.info(f"Опубликована новость текстом (фоллбэк) в канал: {item['title']}")
        except Exception as e_msg:
            logger.error(f"Не удалось отправить текстовую новость в канал: {e_msg}")
            return False

    return posted


async def publish_latest_news(bot: Bot) -> bool:
    """Поиск и публикация одной самой свежей неопубликованной новости в канал."""
    if not config.CHANNEL_ID:
        return False

    news_items = await fetch_rss()
    if not news_items:
        return False

    for item in news_items:
        # Проверяем, была ли уже опубликована эта новость
        if not await db.is_news_posted(item["link"]):
            success = await send_news_item(bot, item)
            if success:
                await db.mark_news_as_posted(item["link"], item["title"])
                logger.info(f"Новость успешно отмечена как опубликованная: {item['title']}")
                return True
            else:
                return False

    return False
