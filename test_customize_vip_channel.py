"""
test_customize_vip_channel.py
Автоматизированные тесты для утилиты кастомизации VIP-канала tools/customize_vip_channel.py.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image

import config
from tools.customize_vip_channel import (
    DEFAULT_TITLE,
    generate_vip_avatar,
    build_channel_description,
    build_welcome_post,
    build_welcome_keyboard,
    run_preview,
    run_apply,
    parse_args
)

TEST_AVATAR_PATH = "tools/test_vip_avatar_temp.png"


class TestCustomizeVipChannel(unittest.IsolatedAsyncioTestCase):

    def tearDown(self):
        if os.path.exists(TEST_AVATAR_PATH):
            try:
                os.remove(TEST_AVATAR_PATH)
            except Exception:
                pass

    def test_avatar_generation(self):
        """Проверка генерации 1024x1024 логотипа через Pillow."""
        out_path = generate_vip_avatar(TEST_AVATAR_PATH)
        self.assertTrue(os.path.exists(out_path))

        with Image.open(out_path) as img:
            self.assertEqual(img.size, (1024, 1024))
            self.assertEqual(img.mode, "RGBA")
            self.assertGreater(os.path.getsize(out_path), 50_000)

    def test_channel_description_length_limit(self):
        """Проверка лимита Telegram API (не более 255 символов) для описания канала."""
        # 1. Дефолтное описание
        desc = build_channel_description(bot_username="test_crypto_bot")
        self.assertLessEqual(len(desc), 255)
        self.assertIn("test_crypto_bot", desc)
        self.assertIn("CryptoRadar", desc)

        # 2. Кастомное длинное описание должно безопасно обрезаться до 255 символов
        long_custom = "A" * 300
        desc_truncated = build_channel_description(custom_desc=long_custom)
        self.assertLessEqual(len(desc_truncated), 255)
        self.assertTrue(desc_truncated.endswith("..."))

    def test_welcome_post_content(self):
        """Проверка содержания приветственного гайд-поста."""
        post = build_welcome_post(project_name="CryptoRadar VIP")
        self.assertIn("CryptoRadar VIP", post)
        self.assertIn("КАК РАБОТАТЬ С НАШИМИ СИГНАЛАМИ", post)
        self.assertIn("TP1", post)
        self.assertIn("TP2", post)
        self.assertIn("TP3", post)
        self.assertIn("Stop-Loss", post)
        self.assertIn("РИСК-МЕНЕДЖМЕНТА", post)
        self.assertIn("1–3%", post)
        self.assertIn("WebApp", post)

    def test_welcome_keyboard(self):
        """Проверка генерации валидной HTTPS-клавиатуры для канала."""
        kb = build_welcome_keyboard(bot_username="my_bot", webapp_url="https://myapp.com")
        self.assertEqual(len(kb.inline_keyboard), 2)
        btn1 = kb.inline_keyboard[0][0]
        btn2 = kb.inline_keyboard[1][0]
        self.assertTrue(btn1.url.startswith("https://"))
        self.assertIn("vip=1", btn1.url)
        self.assertTrue(btn2.url.startswith("https://"))

    async def test_run_preview(self):
        """Проверка безопасного режима превью (не изменяет канал)."""
        exit_code = await run_preview(
            title="💎 VIP Club Preview Test",
            description="Тестовое описание",
            output_path=TEST_AVATAR_PATH
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(os.path.exists(TEST_AVATAR_PATH))

    async def test_run_apply_mocked_bot(self):
        """Проверка применения изменений в Telegram через моки Bot API."""
        mock_bot = AsyncMock()
        mock_bot.id = 123456789
        mock_bot.session = AsyncMock()
        mock_bot.session.close = AsyncMock()

        mock_bot_info = MagicMock()
        mock_bot_info.id = 123456789
        mock_bot_info.username = "test_bot"
        mock_bot.get_me.return_value = mock_bot_info

        mock_chat = MagicMock()
        mock_chat.title = "Old Channel Name"
        mock_chat.type = "channel"
        mock_bot.get_chat.return_value = mock_chat

        mock_member = MagicMock()
        mock_member.status = "administrator"
        mock_bot.get_chat_member.return_value = mock_member

        mock_msg = MagicMock()
        mock_msg.message_id = 999
        mock_bot.send_message.return_value = mock_msg
        mock_bot.pin_chat_message.return_value = True

        with patch("tools.customize_vip_channel.Bot", return_value=mock_bot):
            exit_code = await run_apply(
                title="💎 New Title",
                description="New Description",
                output_path=TEST_AVATAR_PATH
            )
            self.assertEqual(exit_code, 0)

            # Проверяем вызовы Bot API
            mock_bot.set_chat_photo.assert_called_once()
            mock_bot.set_chat_title.assert_called_once_with(
                chat_id=config.VIP_CHANNEL_ID,
                title="💎 New Title"
            )
            mock_bot.set_chat_description.assert_called_once()
            mock_bot.send_message.assert_called_once()
            mock_bot.pin_chat_message.assert_called_once_with(
                chat_id=config.VIP_CHANNEL_ID,
                message_id=999,
                disable_notification=False
            )


if __name__ == "__main__":
    unittest.main()
