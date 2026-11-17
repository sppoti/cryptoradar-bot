import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import BufferedInputFile

from services import news
import config


class TestNewsPosting(unittest.IsolatedAsyncioTestCase):
    def test_extract_image_url(self):
        # 1. Standard img src
        html1 = '<p><img width="1200" height="960" src="https://forklog.com/wp-content/uploads/img.webp" class="thumb" /></p>Some text'
        self.assertEqual(news.extract_image_url(html1), "https://forklog.com/wp-content/uploads/img.webp")

        # 2. Img with data-src
        html2 = '<p><img data-src="https://forklog.com/wp-content/uploads/data_img.png" alt="test" /></p>'
        self.assertEqual(news.extract_image_url(html2), "https://forklog.com/wp-content/uploads/data_img.png")

        # 3. Single quotes
        html3 = "<img src='https://example.com/single.jpg'>"
        self.assertEqual(news.extract_image_url(html3), "https://example.com/single.jpg")

        # 4. No img
        self.assertIsNone(news.extract_image_url("Just plain text with no images"))
        self.assertIsNone(news.extract_image_url(""))
        self.assertIsNone(news.extract_image_url(None))

    def test_clean_html(self):
        raw = (
            "<p><img src='https://example.com/pic.jpg' />Децентрализованная &quot;биржа&quot; "
            "Aster&nbsp;сообщила об усилении защиты &amp; безопасности.</p>"
            "<p>Второй абзац текста.</p>"
        )
        cleaned = news.clean_html(raw)
        self.assertNotIn("<img", cleaned)
        self.assertNotIn("<p>", cleaned)
        self.assertNotIn("</p>", cleaned)
        self.assertIn('"биржа"', cleaned)
        self.assertIn("& безопасности", cleaned)
        self.assertIn("Децентрализованная", cleaned)
        self.assertIn("Второй абзац текста.", cleaned)

    def test_format_news_post_structure_and_no_source_link(self):
        item = {
            "title": "Биткоин & Эфир превысили $100k",
            "description": "Крипторынок демонстрирует мощный рост на фоне притока институционалов.",
            "link": "https://forklog.com/exclusive/bitcoin-surge-2026",
            "image_url": "https://forklog.com/wp-content/uploads/btc.webp"
        }
        post_text = news.format_news_post(item)

        # Проверка обязательных секций заголовка и футера
        self.assertIn("⚡️ <b>СВЕЖИЕ НОВОСТИ КРИПТОРЫНКА</b>", post_text)
        self.assertIn("────────────────────", post_text)
        self.assertIn("📰 <b>Биткоин &amp; Эфир превысили $100k</b>", post_text)
        self.assertIn("Крипторынок демонстрирует мощный рост", post_text)
        self.assertIn("🤖 <b>Сканер сигналов:</b> @ssddssa_bot", post_text)
        self.assertIn("📊 <b>Наш канал:</b> @cryptoradar_live777", post_text)

        # Проверка ПОЛНОГО отсутствия ссылки на источник ForkLog
        self.assertNotIn("forklog.com", post_text)
        self.assertNotIn("Читать подробнее", post_text)
        self.assertNotIn("источник", post_text.lower())
        self.assertNotIn(item["link"], post_text)

    def test_format_news_post_length_limit_1024(self):
        item = {
            "title": "Очень важная и длинная новость крипторынка",
            "description": "А" * 1500,  # Заведомо превышает 1024 символа
            "link": "https://example.com/news/long",
            "image_url": "https://example.com/pic.jpg"
        }
        post_text = news.format_news_post(item, max_len=1024)

        self.assertLessEqual(len(post_text), 1024)
        self.assertIn("...", post_text)
        # Футер должен быть сохранен полностью
        self.assertIn("🤖 <b>Сканер сигналов:</b> @ssddssa_bot", post_text)
        self.assertIn("📊 <b>Наш канал:</b> @cryptoradar_live777", post_text)

    def test_parse_rss_xml(self):
        xml_data = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
            <channel>
                <item>
                    <title>Новость 1: Рост Solana</title>
                    <description>&lt;p&gt;&lt;img src="https://forklog.com/solana.webp" /&gt;Курс SOL вырос на 15%.&lt;/p&gt;</description>
                    <link>https://forklog.com/solana-15</link>
                </item>
                <item>
                    <title>Новость 2: Enclosure Image</title>
                    <description>Текст без тега картинки</description>
                    <link>https://forklog.com/enclosure-news</link>
                    <enclosure url="https://forklog.com/enclosure.jpg" type="image/jpeg" />
                </item>
                <item>
                    <title>Новость 3: Media Content</title>
                    <description>Еще один текст</description>
                    <link>https://forklog.com/media-news</link>
                    <media:content url="https://forklog.com/media.png" medium="image" />
                </item>
            </channel>
        </rss>
        """
        items = news.parse_rss_xml(xml_data)
        self.assertEqual(len(items), 3)

        self.assertEqual(items[0]["title"], "Новость 1: Рост Solana")
        self.assertEqual(items[0]["image_url"], "https://forklog.com/solana.webp")
        self.assertIn("Курс SOL вырос на 15%.", items[0]["description"])
        self.assertNotIn("<img", items[0]["description"])

        self.assertEqual(items[1]["title"], "Новость 2: Enclosure Image")
        self.assertEqual(items[1]["image_url"], "https://forklog.com/enclosure.jpg")

        self.assertEqual(items[2]["title"], "Новость 3: Media Content")
        self.assertEqual(items[2]["image_url"], "https://forklog.com/media.png")

    async def test_send_news_item_with_photo_url_success(self):
        bot = MagicMock()
        bot.send_photo = AsyncMock()
        bot.send_message = AsyncMock()

        item = {
            "title": "Заголовок новости",
            "description": "Описание новости",
            "link": "https://forklog.com/test-news",
            "image_url": "https://forklog.com/test.jpg"
        }

        with patch.object(config, "CHANNEL_ID", -1001234567890):
            result = await news.send_news_item(bot, item)

        self.assertTrue(result)
        bot.send_photo.assert_awaited_once()
        call_kwargs = bot.send_photo.await_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], -1001234567890)
        self.assertEqual(call_kwargs["photo"], "https://forklog.com/test.jpg")
        self.assertEqual(call_kwargs["parse_mode"], "HTML")
        self.assertNotIn("forklog.com", call_kwargs["caption"])
        bot.send_message.assert_not_called()

    async def test_send_news_item_photo_url_fails_then_buffered_bytes_success(self):
        bot = MagicMock()
        # Первый вызов send_photo (по URL) бросает исключение
        # Второй вызов (BufferedInputFile) успешен
        bot.send_photo = AsyncMock(side_effect=[Exception("Telegram download error"), MagicMock()])
        bot.send_message = AsyncMock()

        item = {
            "title": "Заголовок новости 2",
            "description": "Описание новости 2",
            "link": "https://forklog.com/test-news-2",
            "image_url": "https://forklog.com/test2.webp"
        }

        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.read = AsyncMock(return_value=b"fake_image_bytes")

        class MockGetContext:
            async def __aenter__(self):
                return fake_resp
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        class MockSessionContext:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None
            def get(self, *args, **kwargs):
                return MockGetContext()

        with patch.object(config, "CHANNEL_ID", -1001234567890):
            with patch("aiohttp.ClientSession", MockSessionContext):
                result = await news.send_news_item(bot, item)

        self.assertTrue(result)
        self.assertEqual(bot.send_photo.await_count, 2)
        # Второй вызов должен содержать BufferedInputFile
        second_call_kwargs = bot.send_photo.await_args_list[1].kwargs
        self.assertIsInstance(second_call_kwargs["photo"], BufferedInputFile)
        self.assertEqual(second_call_kwargs["photo"].filename, "news.webp")
        bot.send_message.assert_not_called()

    async def test_send_news_item_fallback_to_send_message_disabled_preview(self):
        bot = MagicMock()
        bot.send_photo = AsyncMock()
        bot.send_message = AsyncMock()

        item = {
            "title": "Новость без картинки",
            "description": "Только текст новости",
            "link": "https://forklog.com/test-no-image",
            "image_url": None
        }

        with patch.object(config, "CHANNEL_ID", -1001234567890):
            result = await news.send_news_item(bot, item)

        self.assertTrue(result)
        bot.send_photo.assert_not_called()
        bot.send_message.assert_awaited_once()
        call_kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], -1001234567890)
        self.assertEqual(call_kwargs["parse_mode"], "HTML")
        # ОБЯЗАТЕЛЬНО: disable_web_page_preview=True
        self.assertTrue(call_kwargs["disable_web_page_preview"])
        self.assertNotIn("forklog.com", call_kwargs["text"])

    async def test_publish_latest_news_marks_db_posted(self):
        bot = MagicMock()
        items = [
            {
                "title": "Старая новость",
                "description": "Уже в базе",
                "link": "https://forklog.com/old",
                "image_url": None
            },
            {
                "title": "Свежая новость",
                "description": "Еще не в базе",
                "link": "https://forklog.com/new",
                "image_url": "https://forklog.com/pic.jpg"
            }
        ]

        with patch.object(config, "CHANNEL_ID", -1001234567890):
            with patch("services.news.fetch_rss", AsyncMock(return_value=items)):
                with patch("database.is_news_posted", AsyncMock(side_effect=[True, False])):
                    with patch("database.mark_news_as_posted", AsyncMock()) as mock_mark:
                        with patch("services.news.send_news_item", AsyncMock(return_value=True)) as mock_send:
                            success = await news.publish_latest_news(bot)

        self.assertTrue(success)
        mock_send.assert_awaited_once_with(bot, items[1])
        mock_mark.assert_awaited_once_with(items[1]["link"], items[1]["title"])


if __name__ == "__main__":
    unittest.main()
