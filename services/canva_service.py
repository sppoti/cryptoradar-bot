"""
Canva Cloud Integration Service for CryptoRadar Pro SaaS.
Manages Canva assets, folders, promotional templates, and dynamic design generation
for VIP channel trading signals, B2B partner co-marketing, and viral acquisition funnels.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

logger = logging.getLogger("CanvaService")


class CanvaService:
    """
    Интеграционный сервис Canva для CryptoRadar Pro SaaS.
    Предоставляет методы для работы с облачными проектами Canva,
    генерации промптов/брифов для Canva MCP (create-design, generate-image),
    шаблонами промо-материалов для VIP-канала и локальным рендерингом сигнальных карточек.
    """

    # Идентификаторы и конфигурация проекта в Canva
    FOLDER_ID: str = getattr(config, "CANVA_FOLDER_ID", "FAHbqTG9Vg4")
    FOLDER_NAME: str = getattr(config, "CANVA_FOLDER_NAME", "CryptoRadar Pro SaaS")
    FOLDER_URL: str = getattr(config, "CANVA_FOLDER_URL", f"https://www.canva.com/folder/{FOLDER_ID}")
    TEAM_ID: str = getattr(config, "CANVA_TEAM_ID", "oBZaQa2FDEXm2wgikuzXZ8")
    ACCOUNT_NAME: str = getattr(config, "CANVA_ACCOUNT_NAME", "KIIIER")

    # Фирменная палитра и дизайн-токены (Pitch Black & Tactical Red Monospace Terminal)
    COLORS = {
        "bg_canvas": "#050505",        # Pitch Black холст (абсолютный черный)
        "bg_container": "#0A0A0A",     # Темный терминальный контейнер
        "border_hairline": "#1E1E1E",  # Тонкая hairline рамка
        "divider": "#161616",          # Терминальные разделители
        "card_box": "#0D0D0D",         # Фон плашек метрик
        "text_primary": "#FFFFFF",     # Основной белый текст
        "text_secondary": "#888888",   # Второстепенный серый текст
        "text_muted": "#888888",       # Приглушенный текст лейблов
        "tactical_red": "#FF3333",     # Тактический красный (строго для Stop Loss и бейджа сигнала)
        "bg_primary": "#050505",       # Совместимость
        "bg_surface": "#0A0A0A",       # Совместимость
        "surface_border": "#1E1E1E",   # Совместимость
        "accent_green": "#00FF88",     # Совместимость
        "accent_red": "#FF3333",       # Тактический красный
        "accent_gold": "#F3BA2F",      # Совместимость
        "accent_cyan": "#00F0FF",      # Совместимость
        "accent_purple": "#9945FF",    # Совместимость
        "badge_bg": "#1E1E1E",         # Фон бейджей
    }

    # Стандартные форматы Canva
    FORMATS = {
        "landscape_banner": "1200x675",      # 16:9 Баннер для Telegram-канала / Twitter
        "square_post": "1080x1080",          # 1:1 Квадратный пост
        "vertical_story": "1080x1920",       # 9:16 Telegram Stories / Reels / TikTok
        "channel_cover": "1280x720",         # Обложка канала / YouTube
    }

    def __init__(self, folder_id: Optional[str] = None):
        self.folder_id = folder_id or self.FOLDER_ID
        self.output_dir = Path("static/canva_renders")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_folder_details(self) -> Dict[str, Any]:
        """
        Возвращает метаданные рабочего каталога CryptoRadar Pro SaaS в Canva.
        """
        return {
            "folder_id": self.folder_id,
            "folder_name": self.FOLDER_NAME,
            "folder_url": self.FOLDER_URL,
            "team_id": self.TEAM_ID,
            "account_name": self.ACCOUNT_NAME,
            "status": "connected",
            "environment": "Production Canva Cloud Workspace",
        }

    def get_brand_identity(self) -> Dict[str, Any]:
        """
        Возвращает бренд-гайдлайн и токены для генерации дизайн-макетов.
        """
        return {
            "project_name": getattr(config, "PROJECT_NAME", "CryptoRadar Pro SaaS"),
            "colors": self.COLORS,
            "formats": self.FORMATS,
            "typography": {
                "header": "Space Grotesk / Montserrat Bold",
                "mono_metrics": "JetBrains Mono / Consolas",
                "body": "Inter Regular",
            },
            "brand_voice": "Институциональный хэдж-фондовый тон, минимализм, неоновый акцент на ключевых метриках (RSI, TP/SL, Winrate).",
        }

    def get_available_templates(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Возвращает библиотеку готовых дизайн-шаблонов для VIP-сигналов,
        партнерских промо-акций и сторис.
        """
        templates = [
            {
                "id": "vip_signal_long",
                "name": "VIP Long Signal Banner (16:9)",
                "category": "signals",
                "format": "1200x675",
                "description": "Премиальная карточка лонг-сигнала с RSI-перепроданностью, целями TP1/TP2 и Stop-Loss.",
                "theme": "Neon Green & Obsidian Dark",
                "canva_format": "Banner (Landscape)",
            },
            {
                "id": "vip_signal_short",
                "name": "VIP Short Signal Banner (16:9)",
                "category": "signals",
                "format": "1200x675",
                "description": "Карточка шорт-сигнала со сквизом перекупленности, тейк-профитами и соотношением R:R.",
                "theme": "Crimson Red & Obsidian Dark",
                "canva_format": "Banner (Landscape)",
            },
            {
                "id": "b2b_partner_teaser",
                "name": "B2B Partner Co-Brand Banner (16:9)",
                "category": "partner",
                "format": "1200x675",
                "description": "Промо-баннер для партнерских каналов с реферальной скидкой и кнопкой запуска бота.",
                "theme": "Gold Accent & Electric Cyan",
                "canva_format": "Banner (Landscape)",
            },
            {
                "id": "story_viral_cheatcode",
                "name": "Viral Vertical Story (9:16)",
                "category": "viral_social",
                "format": "1080x1920",
                "description": "Вертикальная сторис для TikTok/Reels/Telegram с хуком «Чит-код китов» и стрелкой на бота.",
                "theme": "Cyberpunk Neon Green Glow",
                "canva_format": "Instagram Story",
            },
            {
                "id": "market_wrap_daily",
                "name": "Daily Institutional Market Wrap (1:1)",
                "category": "analytics",
                "format": "1080x1080",
                "description": "Квадратный дайджест дня: карта рынка, доминация BTC, индекс страха/жадности.",
                "theme": "Institutional Minimalist Dark",
                "canva_format": "Instagram Post",
            },
            {
                "id": "tma_terminal_showcase",
                "name": "Telegram Mini App WebApp Terminal Showcase (16:9)",
                "category": "product",
                "format": "1200x675",
                "description": "Презентация Mini App: темный интерфейс без VPN, живой TradingView и моментальный запуск.",
                "theme": "Deep Electric Cyan & Glassmorphism",
                "canva_format": "Banner (Landscape)",
            },
        ]

        if category:
            return [t for t in templates if t["category"] == category]
        return templates

    def get_template_by_id(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Поиск шаблона по его ID."""
        for t in self.get_available_templates():
            if t["id"] == template_id:
                return t
        return None

    def generate_signal_banner_brief(
        self,
        symbol: str,
        signal_type: str,
        entry_price: float,
        tp1: float,
        tp2: float,
        stop_loss: float,
        rsi_val: float,
        timeframe: str = "1H",
        winrate_pct: int = 94,
        notes: str = ""
    ) -> Dict[str, Any]:
        """
        Генерирует спецификацию дизайна и структурированный бриф для вызова Canva MCP create-design.
        """
        is_long = signal_type.upper() == "LONG"
        action_text = "🟢 LONG BUY SETUP" if is_long else "🔴 SHORT SELL SETUP"
        accent_color = self.COLORS["accent_green"] if is_long else self.COLORS["accent_red"]
        risk_reward = round(abs(tp2 - entry_price) / max(abs(entry_price - stop_loss), 0.0001), 2)

        brief_text = (
            f"Institutional crypto trading signal banner for VIP channel. "
            f"Asset: {symbol}. Signal: {action_text} on {timeframe} timeframe. "
            f"Entry: {entry_price:,.2f}, Target 1: {tp1:,.2f}, Target 2: {tp2:,.2f}, Stop Loss: {stop_loss:,.2f}. "
            f"RSI Indicator: {rsi_val:.1f} (Extreme divergence detected). Calculated Winrate: {winrate_pct}%, Risk/Reward: {risk_reward}:1. "
            f"Dark theme with deep obsidian background ({self.COLORS['bg_primary']}), glassmorphic cards, "
            f"neon glow accents in {accent_color}, TradingView chart outline in background. "
            f"Minimalistic, modern, high conversion hedge-fund look."
        )

        return {
            "template_id": "vip_signal_long" if is_long else "vip_signal_short",
            "format": "Banner (Landscape)",
            "canva_folder_id": self.folder_id,
            "user_intent": f"Create Canva banner for VIP signal {symbol} {signal_type}",
            "brief": brief_text,
            "data": {
                "symbol": symbol,
                "signal_type": signal_type.upper(),
                "action_text": action_text,
                "timeframe": timeframe,
                "entry_price": entry_price,
                "tp1": tp1,
                "tp2": tp2,
                "stop_loss": stop_loss,
                "rsi_val": rsi_val,
                "winrate_pct": winrate_pct,
                "risk_reward": f"{risk_reward}:1",
                "notes": notes or ("Oversold RSI Divergence" if is_long else "Overbought Resistance Exhaustion"),
                "accent_color": accent_color,
                "folder_url": self.FOLDER_URL,
            }
        }

    def generate_promo_banner_brief(
        self,
        template_id: str = "b2b_partner_teaser",
        partner_code: Optional[str] = None,
        bot_username: str = "@cryptoradar_live_bot",
        project_name: str = "CryptoRadar VIP",
        discount_badge: str = "3 ДНЯ VIP БЕСПЛАТНО"
    ) -> Dict[str, Any]:
        """
        Генерирует бриф для партнерских рекламных баннеров и промо-акций.
        """
        clean_bot = bot_username.replace("@", "")
        ref_slug = partner_code or "community"
        ref_link = f"https://t.me/{clean_bot}?start=ref_{ref_slug}"

        brief_text = (
            f"High-converting promotional banner for crypto community channel. "
            f"Headline: '{project_name} Terminal - Automated Whale Radar'. "
            f"Badge: '{discount_badge}'. "
            f"Key selling points: 24/7 Binance/Bybit RSI scan, TradingView in Telegram, 92%+ winrate AI forecast. "
            f"Call to action: 'Launch terminal: t.me/{clean_bot}?start=ref_{ref_slug}'. "
            f"Aesthetic: Dark mode obsidian #{self.COLORS['bg_primary']}, neon cyan #{self.COLORS['accent_cyan']} and gold accents, "
            f"futuristic fintech HUD badges."
        )

        return {
            "template_id": template_id,
            "format": "Banner (Landscape)",
            "canva_folder_id": self.folder_id,
            "user_intent": f"Generate promo banner for partner {ref_slug}",
            "brief": brief_text,
            "data": {
                "headline": f"{project_name} • Institutional Radar",
                "badge": discount_badge,
                "partner_slug": ref_slug,
                "partner_ref_link": ref_link,
                "bot_username": f"@{clean_bot}",
                "folder_url": self.FOLDER_URL,
            }
        }

    def generate_story_brief(
        self,
        hook_title: str = "Чит-код китов: как заходить до пампа",
        bot_username: str = "@cryptoradar_live_bot",
        partner_code: Optional[str] = None,
        highlight_metric: str = "+320% ROI",
        subtitle: str = "Инсайдерский AI сканер аномалий"
    ) -> Dict[str, Any]:
        """
        Генерирует спецификацию вертикального вирусного креатива 9:16 (Stories/Shorts/TikTok).
        """
        clean_bot = bot_username.replace("@", "")
        ref_suffix = f"?start=ref_{partner_code}" if partner_code else ""

        brief_text = (
            f"Vertical 9:16 viral mobile graphic for Instagram/Telegram Stories. "
            f"Bold hook text at top: '{hook_title}'. "
            f"Big central stat badge: '{highlight_metric}'. "
            f"Subtitle: '{subtitle}'. "
            f"Phone mockup in middle showing clean dark-mode crypto terminal graph with RSI turning green. "
            f"Bottom swipe/tap sticker pointing to '@{clean_bot}'. "
            f"Color palette: Ultra-dark background with electric neon green #{self.COLORS['accent_green']} glow."
        )

        return {
            "template_id": "story_viral_cheatcode",
            "format": "Instagram Story",
            "canva_folder_id": self.folder_id,
            "user_intent": "Generate 9:16 vertical viral social story",
            "brief": brief_text,
            "data": {
                "hook_title": hook_title,
                "highlight_metric": highlight_metric,
                "subtitle": subtitle,
                "bot_username": f"@{clean_bot}",
                "link": f"https://t.me/{clean_bot}{ref_suffix}",
                "folder_url": self.FOLDER_URL,
            }
        }

    def export_canva_mcp_payload(self, brief_spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Преобразует сгенерированный бриф в готовые параметры для вызова canva_canva MCP инструмента create-design.
        """
        return {
            "brief": brief_spec["brief"],
            "format": brief_spec.get("format", "Banner (Landscape)"),
            "user_intent": brief_spec.get("user_intent", "Create design for CryptoRadar Pro SaaS"),
        }

    def render_local_signal_card(
        self,
        symbol: Any = "BTCUSDT",
        signal_type: str = "LONG",
        entry_price: float = 0.0,
        tp1: float = 0.0,
        tp2: float = 0.0,
        stop_loss: float = 0.0,
        rsi_val: float = 50.0,
        timeframe: str = "1H",
        winrate_pct: int = 94,
        notes: str = "",
        output_filename: Optional[str] = None
    ) -> str:
        """
        Локальный высокопроизводительный рендерер сигнальной графической карточки (1200x675) на базе Pillow.
        Оформлен в утвержденном терминальном стиле Pitch Black & Tactical Red Monospace:
        - Холст: #050505 (pitch black)
        - Контейнер: #0A0A0A с hairline рамкой #1E1E1E
        - Разделители: #161616
        - Текст: #FFFFFF / #888888
        - Тактический красный: #FF3333 строго для Stop Loss и бейджа сигнала
        - Полное отсутствие свечений, неоновых градиентов и размытий
        - Моноширинный шрифт Consolas / Courier New / Lucida Console
        """
        risk_reward_str = ""
        if isinstance(symbol, dict):
            analysis = symbol
            sym_raw = analysis.get("symbol") or analysis.get("ticker", "BTCUSDT")
            bias_str = str(analysis.get("bias", "LONG")).lower()
            is_sh = "short" in bias_str
            signal_type = "SHORT" if is_sh else "LONG"
            entry_price = float(analysis.get("price") or 0.0)
            tp1 = float(analysis.get("tp1_price") or (entry_price * (0.97 if is_sh else 1.03)))
            tp2 = float(analysis.get("tp2_price") or (entry_price * (0.95 if is_sh else 1.06)))
            stop_loss = float(analysis.get("stop_loss_price") or (entry_price * (1.02 if is_sh else 0.98)))
            indicators = analysis.get("indicators", {}) if isinstance(analysis.get("indicators"), dict) else {}
            rsi_val = float(indicators.get("rsi_1h") or 50.0)
            timeframe = "1H"
            winrate_pct = int(analysis.get("probability") or 94)
            notes = notes or str(analysis.get("summary") or analysis.get("bias_badge") or "")
            risk_reward_str = str(analysis.get("risk_reward") or "")
            symbol = sym_raw

        width, height = 1200, 675
        is_long = signal_type.upper() == "LONG"

        # Расчет Risk/Reward если не задан
        if not risk_reward_str:
            rr_val = round(abs(tp2 - entry_price) / max(abs(entry_price - stop_loss), 0.0001), 2)
            risk_reward_str = f"1:{rr_val}"

        # Создание холста: Pitch Black (#050505) - строго без градиентов и без свечений
        img = Image.new("RGB", (width, height), color="#050505")
        draw = ImageDraw.Draw(img)

        # Загрузка шрифтов (моноширинные)
        font_large, font_title, font_medium, font_mono, font_small = self._load_fonts()

        # Центральный терминальный контейнер (#0A0A0A с hairline рамкой #1E1E1E)
        card_rect = [40, 40, 1160, 635]
        draw.rounded_rectangle(card_rect, radius=6, fill="#0A0A0A", outline="#1E1E1E", width=1)

        # 1. Верхняя панель: Бренд + Терминальный статус
        draw.text((65, 68), "CRYPTORADAR PRO // QUANTITATIVE TERMINAL", fill="#888888", font=font_small)
        status_header = f"NODE: VIP_AUTOPILOT  |  SYNC: #{self.FOLDER_ID}"
        draw.text((790, 68), status_header, fill="#888888", font=font_small)

        # Разделитель верхней панели (#161616)
        draw.line([65, 108, 1135, 108], fill="#161616", width=1)

        # 2. Секция тикера и бейджа сигнала
        clean_sym = symbol.replace("USDT", "").replace("/", "").upper()
        ticker_display = f"#{clean_sym}/USDT"
        draw.text((65, 132), ticker_display, fill="#FFFFFF", font=font_large)

        # Бейдж сигнала: строго тактический красный (#FF3333) для Stop Loss и бейджа сигнала
        action_title = "LONG BUY SETUP" if is_long else "SHORT SELL SETUP"
        badge_bbox = draw.textbbox((0, 0), action_title, font=font_title)
        badge_text_w = badge_bbox[2] - badge_bbox[0]
        badge_text_h = badge_bbox[3] - badge_bbox[1]

        # Позиционирование бейджа справа от тикера
        ticker_bbox = draw.textbbox((65, 132), ticker_display, font=font_large)
        badge_x1 = max(420, ticker_bbox[2] + 30)
        badge_y1 = 138
        badge_w = badge_text_w + 32
        badge_h = 44
        draw.rounded_rectangle([badge_x1, badge_y1, badge_x1 + badge_w, badge_y1 + badge_h], radius=4, fill="#FF3333")
        draw.text((badge_x1 + 16, badge_y1 + (badge_h - badge_text_h) // 2 - 2), action_title, fill="#050505", font=font_title)

        # Строка параметров: TF, Winrate, Risk/Reward
        meta_line = f"TIMEFRAME: {timeframe}  |  MODEL CONFIDENCE: {winrate_pct}%  |  RISK/REWARD: {risk_reward_str}"
        draw.text((65, 195), meta_line, fill="#888888", font=font_small)

        # Разделитель перед метриками (#161616)
        draw.line([65, 232, 1135, 232], fill="#161616", width=1)

        # 3. Сетка параметров цен: Entry, TP1, TP2, Stop Loss
        col_w = 250
        gap = 23
        start_x = 65
        box_y1 = 255
        box_y2 = 365

        metrics = [
            ("ENTRY PRICE", f"${entry_price:,.2f}", "#FFFFFF"),
            ("TAKE PROFIT 1", f"${tp1:,.2f}", "#FFFFFF"),
            ("TAKE PROFIT 2 (RUNNER)", f"${tp2:,.2f}", "#FFFFFF"),
            ("STOP LOSS", f"${stop_loss:,.2f}", "#FF3333"),  # Строго тактический красный #FF3333
        ]

        for i, (label, val, val_color) in enumerate(metrics):
            cx = start_x + (i * (col_w + gap))
            # Терминальный бокс для метрики (#0D0D0D с рамкой #1E1E1E)
            draw.rounded_rectangle([cx, box_y1, cx + col_w, box_y2], radius=4, fill="#0D0D0D", outline="#1E1E1E", width=1)
            draw.text((cx + 16, box_y1 + 18), label, fill="#888888", font=font_small)
            draw.text((cx + 16, box_y1 + 58), val, fill=val_color, font=font_mono)

        # Разделитель перед нижними блоками (#161616)
        draw.line([65, 392, 1135, 392], fill="#161616", width=1)

        # 4. Нижняя секция: 2 терминальных блока
        lower_y1 = 415
        lower_y2 = 610

        # Левый блок: Осцилляторы и квантовая телеметрия
        draw.rounded_rectangle([65, lower_y1, 680, lower_y2], radius=6, fill="#0D0D0D", outline="#1E1E1E", width=1)
        draw.text((85, lower_y1 + 20), "> QUANTITATIVE TELEMETRY // OSCILLATORS", fill="#888888", font=font_small)
        draw.text((85, lower_y1 + 52), f"RSI MOMENTUM: {rsi_val:.1f}", fill="#FFFFFF", font=font_title)

        status_text = "Oversold Zone (Smart-Money Reversal)" if is_long else "Overbought Extreme (Exhaustion Dump)"
        draw.text((85, lower_y1 + 95), f"REGIME: {status_text}", fill="#888888", font=font_small)
        if notes:
            clean_note = (notes[:52] + "...") if len(notes) > 55 else notes
            draw.text((85, lower_y1 + 125), f"QUANT NOTE: {clean_note}", fill="#888888", font=font_small)
        else:
            draw.text((85, lower_y1 + 125), "QUANT NOTE: Volume and momentum confluence confirmed", fill="#888888", font=font_small)
        draw.text((85, lower_y1 + 155), "EXECUTION: Fix 40% at TP1. Move SL to Breakeven.", fill="#888888", font=font_small)

        # Правый блок: Терминал и доступ
        draw.rounded_rectangle([705, lower_y1, 1135, lower_y2], radius=6, fill="#0D0D0D", outline="#1E1E1E", width=1)
        draw.text((725, lower_y1 + 20), "> TERMINAL RADAR NODE // ACCESS", fill="#888888", font=font_small)
        draw.text((725, lower_y1 + 52), "CRYPTORADAR VIP AUTOPILOT", fill="#FFFFFF", font=font_title)
        draw.text((725, lower_y1 + 95), "Real-time 24/7 Binance & Bybit Quant Engine", fill="#888888", font=font_small)
        draw.text((725, lower_y1 + 125), "Mini App: WebApp / TradingView Engine", fill="#888888", font=font_small)
        draw.text((725, lower_y1 + 155), "LAUNCH: t.me/cryptoradar_live_bot", fill="#FFFFFF", font=font_small)

        # 5. Сохранение файла
        if output_filename:
            target_p = Path(output_filename)
            if target_p.is_absolute() or len(target_p.parts) > 1:
                filepath = target_p
            else:
                filepath = self.output_dir / target_p
        else:
            clean_symbol = symbol.replace("/", "_").replace("\\", "_").lower()
            filename = f"signal_card_{clean_symbol}_{signal_type.lower()}.png"
            filepath = self.output_dir / filename

        filepath.parent.mkdir(parents=True, exist_ok=True)
        img.save(filepath, format="PNG", quality=95)

        logger.info(f"Локальная сигнальная карточка сгенерирована: {filepath}")
        return str(filepath)

    def _load_fonts(self) -> Tuple[Any, Any, Any, Any, Any]:
        """Загрузка системных моноширинных шрифтов (Consolas, Courier, Lucida Console) с безопасным фоллбеком."""
        mono_fonts = [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "C:/Windows/Fonts/lucon.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/System/Library/Fonts/SFNSMono.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]

        selected_font = None
        for p in mono_fonts:
            if os.path.exists(p):
                selected_font = p
                break

        if selected_font:
            try:
                f_large = ImageFont.truetype(selected_font, 44)
                f_title = ImageFont.truetype(selected_font, 24)
                f_med = ImageFont.truetype(selected_font, 20)
                f_mono = ImageFont.truetype(selected_font, 22)
                f_small = ImageFont.truetype(selected_font, 15)
                return f_large, f_title, f_med, f_mono, f_small
            except Exception as e:
                logger.warning(f"Не удалось загрузить шрифт TrueType: {e}, переключение на дефолтный")

        def_font = ImageFont.load_default()
        return def_font, def_font, def_font, def_font, def_font


# Глобальный синглтон сервиса
canva_service = CanvaService()


def render_local_signal_card(*args: Any, **kwargs: Any) -> str:
    """Глобальная функция-обертка для рендеринга карточки сигнала."""
    return canva_service.render_local_signal_card(*args, **kwargs)

