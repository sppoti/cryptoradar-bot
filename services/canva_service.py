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

    # Фирменная палитра и дизайн-токены (Cyberpunk / Institutional Crypto Dark Mode)
    COLORS = {
        "bg_primary": "#0B0E14",       # Глубокий обсидиановый фон
        "bg_surface": "#151A24",       # Карточка / контейнер с эффектом матового стекла
        "surface_border": "#2A3245",   # Тонкая рамка контейнера
        "accent_green": "#00FF88",     # Лонг / Перепроданность / Тейк-Профит
        "accent_red": "#FF3366",       # Шорт / Перекупленность / Стоп-Лосс
        "accent_gold": "#F3BA2F",      # Звезды Telegram Stars / VIP бейджи
        "accent_cyan": "#00F0FF",      # Радар / TradingView графики
        "accent_purple": "#9945FF",    # AI Квантовый автопилот / Смарт-мани
        "text_primary": "#FFFFFF",     # Основной белый текст
        "text_secondary": "#94A3B8",   # Второстепенный серый текст (Slate-400)
        "badge_bg": "#1E293B",         # Фон бейджей
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
        Обеспечивает 100% автономность сервиса при работе оффлайн или без активного интернет-соединения с Canva.
        Поддерживает передачу как отдельных аргументов, так и комплексного словаря анализа (ai_analytics.analyze_asset).
        """
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
            notes = notes or str(analysis.get("bias_badge") or "")
            symbol = sym_raw
        width, height = 1200, 675
        is_long = signal_type.upper() == "LONG"
        accent_hex = self.COLORS["accent_green"] if is_long else self.COLORS["accent_red"]

        # Создание базового темного холста
        img = Image.new("RGBA", (width, height), color="#0B0E14")
        draw = ImageDraw.Draw(img)

        # Фоновый неоновый градиент / размытие
        glow_color = (0, 255, 136, 18) if is_long else (255, 51, 102, 18)
        draw.ellipse([800, -100, 1300, 400], fill=glow_color)
        draw.ellipse([-100, 400, 400, 800], fill=(0, 240, 255, 12))

        # Загрузка шрифтов
        font_large, font_title, font_medium, font_mono, font_small = self._load_fonts()

        # Центральная стеклянная карточка (Glassmorphism container)
        card_rect = [50, 50, 1150, 625]
        draw.rounded_rectangle(card_rect, radius=20, fill="#131822", outline="#222B3D", width=2)

        # Верхняя панель: Бренд + Статус
        draw.text((85, 80), "CRYPTORADAR PRO", fill="#94A3B8", font=font_small)
        draw.text((250, 80), "• VIP QUANTITATIVE SIGNAL", fill=self.COLORS["accent_cyan"], font=font_small)

        # Бейдж папки Canva
        folder_badge = f"CANVA SYNC: #{self.FOLDER_ID}"
        draw.text((900, 80), folder_badge, fill="#64748B", font=font_small)

        # Тикер и направление сделки
        action_title = "LONG BUY" if is_long else "SHORT SELL"
        draw.text((85, 120), symbol.upper(), fill="#FFFFFF", font=font_large)
        
        # Цветная плашка направления
        badge_w = 230
        draw.rounded_rectangle([420, 130, 420 + badge_w, 185], radius=10, fill=accent_hex)
        draw.text((440, 140), action_title, fill="#0B0E14", font=font_title)

        # Таймфрейм и Winrate
        tf_badge = f"TF: {timeframe}  |  WINRATE: {winrate_pct}%"
        draw.text((425, 195), tf_badge, fill="#94A3B8", font=font_small)

        # Разделительная линия
        draw.line([85, 240, 1115, 240], fill="#1E2738", width=1)

        # Сетка параметров: Entry, TP1, TP2, Stop Loss
        col_w = 245
        start_x = 85
        y_label = 270
        y_val = 305

        metrics = [
            ("ENTRY PRICE", f"${entry_price:,.2f}", "#FFFFFF"),
            ("TAKE PROFIT 1", f"${tp1:,.2f}", self.COLORS["accent_green"]),
            ("TAKE PROFIT 2 (MOON)", f"${tp2:,.2f}", self.COLORS["accent_green"]),
            ("STOP LOSS", f"${stop_loss:,.2f}", self.COLORS["accent_red"]),
        ]

        for i, (label, val, val_color) in enumerate(metrics):
            cx = start_x + (i * col_w)
            # Контейнер для каждой метрики
            draw.rounded_rectangle([cx, y_label - 10, cx + col_w - 20, y_val + 50], radius=12, fill="#182030", outline="#26334D", width=1)
            draw.text((cx + 15, y_label), label, fill="#64748B", font=font_small)
            draw.text((cx + 15, y_val), val, fill=val_color, font=font_mono)

        # Нижняя секция: RSI индикаторная шкала и примечания
        box_y = 390
        draw.rounded_rectangle([85, box_y, 700, 570], radius=14, fill="#182030", outline="#26334D", width=1)
        draw.text((110, box_y + 20), "RSI MOMENTUM DIVERGENCE", fill="#94A3B8", font=font_small)
        
        rsi_color = self.COLORS["accent_green"] if rsi_val <= 30 else (self.COLORS["accent_red"] if rsi_val >= 70 else "#F3BA2F")
        draw.text((110, box_y + 55), f"RSI: {rsi_val:.1f}", fill=rsi_color, font=font_title)
        
        status_text = "Oversold Zone (Smart-Money Reversal)" if is_long else "Overbought Extreme (Exhaustion Dump)"
        draw.text((110, box_y + 110), f"Status: {status_text}", fill="#CBD5E1", font=font_small)
        if notes:
            draw.text((110, box_y + 135), f"Quant Note: {notes}", fill="#94A3B8", font=font_small)

        # Правый блок: Подписка и запуск бота
        draw.rounded_rectangle([730, box_y, 1115, 570], radius=14, fill="#1A2338", outline="#2D3C5E", width=1)
        draw.text((755, box_y + 20), "EXCLUSIVE VIP RADAR", fill=self.COLORS["accent_gold"], font=font_small)
        draw.text((755, box_y + 55), "Автопилот в Telegram", fill="#FFFFFF", font=font_title)
        draw.text((755, box_y + 110), "Живой сканер • Тейк-профиты • Stars / СБП", fill="#94A3B8", font=font_small)
        draw.text((755, box_y + 135), "Запуск: t.me/cryptoradar_live_bot", fill=self.COLORS["accent_cyan"], font=font_small)

        # Сохранение файла
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
        """Вспомогательный загрузчик системных шрифтов с безопасным фоллбеком."""
        font_paths = [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/consola.ttf",
        ]
        
        primary_font = None
        for p in font_paths:
            if os.path.exists(p):
                primary_font = p
                break

        if primary_font:
            try:
                f_large = ImageFont.truetype(primary_font, 56)
                f_title = ImageFont.truetype(primary_font, 32)
                f_med = ImageFont.truetype(primary_font, 24)
                f_mono = ImageFont.truetype("C:/Windows/Fonts/consola.ttf" if os.path.exists("C:/Windows/Fonts/consola.ttf") else primary_font, 26)
                f_small = ImageFont.truetype(primary_font, 18)
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

