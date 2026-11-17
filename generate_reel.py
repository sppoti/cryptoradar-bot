import os
import re
import sys
import math
import subprocess
import asyncio
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg
from gtts import gTTS

import config
from services import scanner

VIDEOS_DIR = os.path.join(os.path.dirname(__file__), "videos")
os.makedirs(VIDEOS_DIR, exist_ok=True)

WIDTH = 1080
HEIGHT = 1920
FPS = 30

FONT_DIR = os.environ.get("WINDIR", "C:\\Windows") + "\\Fonts"
FONT_BOLD_PATH = os.path.join(FONT_DIR, "arialbd.ttf")
FONT_REG_PATH = os.path.join(FONT_DIR, "arial.ttf")

def get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def get_audio_duration(audio_path: str, ffmpeg_exe: str) -> float:
    p = subprocess.Popen([ffmpeg_exe, "-i", audio_path], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    _, err = p.communicate()
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", err.decode("utf-8", errors="ignore"))
    if match:
        h, m, s = match.groups()
        return int(h) * 3600 + int(m) * 60 + float(s)
    return 14.0

async def fetch_crypto_data(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    ticker = await scanner.get_ticker_24hr(symbol)
    price = float(ticker.get("lastPrice", 0)) if ticker else 65000.0
    change = float(ticker.get("priceChangePercent", 0)) if ticker else 1.2
    rsi_1h = await scanner.calculate_rsi(symbol, "1h", 14) or 50.0
    rsi_4h = await scanner.calculate_rsi(symbol, "4h", 14) or 48.0
    
    if rsi_1h <= 35:
        verdict = "СИГНАЛ В ЛОНГ (ПЕРЕПРОДАН)"
        color = (0, 230, 118)
    elif rsi_1h >= 65:
        verdict = "СИГНАЛ В ШОРТ (ПЕРЕКУПЛЕН)"
        color = (255, 23, 68)
    else:
        verdict = "БОКОВИК / НАКОПЛЕНИЕ"
        color = (0, 229, 255)
        
    return {
        "symbol": symbol.replace("USDT", ""),
        "price": price,
        "change": change,
        "rsi_1h": rsi_1h,
        "rsi_4h": rsi_4h,
        "verdict": verdict,
        "verdict_color": color
    }

def draw_frame(
    data: Dict[str, Any],
    t: float,
    duration: float,
    bot_tag: str = "@ssddssa_bot",
    channel_tag: str = "Канал: @cryptoradar_live777"
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), (11, 14, 20))
    draw = ImageDraw.Draw(img)
    
    grid_spacing = 80
    for x in range(0, WIDTH, grid_spacing):
        draw.line([(x, 0), (x, HEIGHT)], fill=(20, 26, 36), width=1)
    for y in range(0, HEIGHT, grid_spacing):
        draw.line([(0, y), (WIDTH, y)], fill=(20, 26, 36), width=1)
        
    scan_y = int((HEIGHT * 0.2) + ((math.sin(t * 3.0) + 1) / 2) * (HEIGHT * 0.6))
    for dy in range(-20, 21):
        alpha_factor = 1.0 - abs(dy) / 20.0
        line_color = (0, int(229 * alpha_factor * 0.4), int(255 * alpha_factor * 0.4))
        draw.line([(0, scan_y + dy), (WIDTH, scan_y + dy)], fill=line_color, width=1)
    draw.line([(0, scan_y), (WIDTH, scan_y)], fill=(0, 255, 200), width=3)
    
    # 1. Верхняя плашка
    badge_w, badge_h = 680, 70
    badge_x, badge_y = (WIDTH - badge_w) // 2, 120
    draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=35, fill=(18, 30, 49), outline=(0, 229, 255), width=2)
    f_badge = get_font(28, bold=True)
    draw.text((badge_x + 35, badge_y + 18), "⚡ CRYPTORADAR AI • АВТОСКАНЕР", fill=(0, 229, 255), font=f_badge)
    
    # 2. Главный хук
    f_title = get_font(56, bold=True)
    draw.text((WIDTH // 2, 250), "БИТКОИН: ТОЧКА ВХОДА?", fill=(255, 255, 255), font=f_title, anchor="mm")
    f_sub = get_font(34, bold=True)
    draw.text((WIDTH // 2, 330), "РАСЧЕТ ИНДИКАТОРА RSI С БИРЖИ", fill=(160, 180, 205), font=f_sub, anchor="mm")
    
    # 3. Карточка актива
    card_w, card_h = 920, 680
    card_x = (WIDTH - card_w) // 2
    card_y = 400
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h], radius=30, fill=(16, 22, 34), outline=(35, 48, 70), width=3)
    
    f_coin = get_font(44, bold=True)
    draw.text((card_x + 60, card_y + 50), f"🔥 {data['symbol']} / USDT", fill=(255, 255, 255), font=f_coin)
    
    f_price = get_font(72, bold=True)
    price_str = f"${data['price']:,.2f}" if data['price'] >= 1 else f"${data['price']:.4f}"
    draw.text((card_x + 60, card_y + 120), price_str, fill=(0, 229, 255), font=f_price)
    
    chg = data['change']
    chg_color = (0, 230, 118) if chg >= 0 else (255, 23, 68)
    chg_text = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
    draw.rounded_rectangle([card_x + card_w - 240, card_y + 60, card_x + card_w - 50, card_y + 125], radius=18, fill=chg_color)
    f_chg = get_font(32, bold=True)
    draw.text((card_x + card_w - 145, card_y + 92), chg_text, fill=(0, 0, 0), font=f_chg, anchor="mm")
    
    draw.line([(card_x + 50, card_y + 220), (card_x + card_w - 50, card_y + 220)], fill=(30, 42, 60), width=2)
    
    f_rsi_lbl = get_font(34, bold=False)
    draw.text((card_x + 60, card_y + 250), "Индекс RSI (1 час):", fill=(180, 195, 215), font=f_rsi_lbl)
    
    f_rsi_val = get_font(48, bold=True)
    draw.text((card_x + card_w - 60, card_y + 250), f"{data['rsi_1h']:.1f}", fill=(255, 255, 255), font=f_rsi_val, anchor="ra")
    
    # Шкала RSI
    bar_x, bar_y = card_x + 60, card_y + 325
    bar_w, bar_h = card_w - 120, 26
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=13, fill=(25, 34, 48))
    draw.rectangle([bar_x, bar_y, bar_x + int(bar_w * 0.3), bar_y + bar_h], fill=(0, 200, 100))
    draw.rectangle([bar_x + int(bar_w * 0.7), bar_y, bar_x + bar_w, bar_y + bar_h], fill=(220, 30, 60))
    
    rsi_norm = min(max(data['rsi_1h'] / 100.0, 0.0), 1.0)
    pin_x = bar_x + int(bar_w * rsi_norm)
    draw.ellipse([pin_x - 18, bar_y - 6, pin_x + 18, bar_y + bar_h + 6], fill=(255, 255, 255), outline=(0, 229, 255), width=4)
    
    f_scale = get_font(24, bold=False)
    draw.text((bar_x, bar_y + 36), "0 (Oversold)", fill=(0, 230, 118), font=f_scale)
    draw.text((bar_x + bar_w // 2, bar_y + 36), "50 (Нейтрально)", fill=(130, 145, 165), font=f_scale, anchor="ma")
    draw.text((bar_x + bar_w, bar_y + 36), "100 (Overbought)", fill=(255, 80, 80), font=f_scale, anchor="ra")
    
    # Вердикт
    verdict_y = card_y + 440
    pulse = (math.sin(t * 6.0) + 1.0) / 2.0
    v_fill = data["verdict_color"]
    draw.rounded_rectangle([card_x + 50, verdict_y, card_x + card_w - 50, verdict_y + 160], radius=24, fill=(20, 28, 42), outline=v_fill, width=int(3 + pulse * 3))
    
    f_v_lbl = get_font(26, bold=True)
    draw.text((WIDTH // 2, verdict_y + 30), "ВЕРДИКТ АВТОСКАНЕРА:", fill=(160, 180, 205), font=f_v_lbl, anchor="mm")
    
    f_v_val = get_font(38, bold=True)
    draw.text((WIDTH // 2, verdict_y + 95), data["verdict"], fill=v_fill, font=f_v_val, anchor="mm")
    
    # 4. Свечи
    chart_y = 1140
    chart_h = 240
    draw.line([(80, chart_y + chart_h), (WIDTH - 80, chart_y + chart_h)], fill=(40, 50, 70), width=2)
    
    candle_w = 26
    step = 55
    start_x = 110
    for i in range(16):
        cx = start_x + i * step
        val = math.sin((i * 0.6) + (t * 2.0)) * 60 + 100
        is_green = (i % 3 != 1)
        c_col = (0, 230, 118) if is_green else (255, 23, 68)
        
        draw.line([(cx, chart_y + chart_h - int(val + 30)), (cx, chart_y + chart_h - int(val - 30))], fill=c_col, width=2)
        draw.rectangle([cx - candle_w // 2, chart_y + chart_h - int(val + 15), cx + candle_w // 2, chart_y + chart_h - int(val - 15)], fill=c_col)
        
    # 5. Призыв к действию (CTA)
    cta_w, cta_h = 920, 360
    cta_x = (WIDTH - cta_w) // 2
    cta_y = 1440
    draw.rounded_rectangle([cta_x, cta_y, cta_x + cta_w, cta_y + cta_h], radius=32, fill=(15, 24, 38), outline=(0, 229, 255), width=3)
    
    f_cta_head = get_font(38, bold=True)
    draw.text((WIDTH // 2, cta_y + 55), "🚀 ЗАБИРАЙ СКАНЕР В TELEGRAM:", fill=(255, 255, 255), font=f_cta_head, anchor="mm")
    
    bot_pill_w, bot_pill_h = 760, 90
    bp_x = (WIDTH - bot_pill_w) // 2
    bp_y = cta_y + 115
    draw.rounded_rectangle([bp_x, bp_y, bp_x + bot_pill_w, bp_y + bot_pill_h], radius=24, fill=(0, 229, 255))
    f_bot_name = get_font(42 if len(bot_tag) > 14 else 48, bold=True)
    draw.text((WIDTH // 2, bp_y + 45), bot_tag, fill=(10, 15, 25), font=f_bot_name, anchor="mm")
    
    f_cta_sub = get_font(30, bold=True)
    draw.text((WIDTH // 2, cta_y + 245), channel_tag, fill=(0, 230, 118), font=f_cta_sub, anchor="mm")
    
    f_cta_hint = get_font(26, bold=False)
    draw.text((WIDTH // 2, cta_y + 305), "Ссылка для входа закреплена в профиле 👆", fill=(170, 190, 210), font=f_cta_hint, anchor="mm")
    
    return img

async def generate_reel(
    symbol: str = "BTCUSDT",
    bot_username: str = "ssddssa_bot",
    channel_tag: str = "@cryptoradar_live777",
    output_filename: str = "reel_btc_signal.mp4"
) -> str:
    print(f"⏳ Получаем актуальные данные по рынку ({symbol})...")
    data = await fetch_crypto_data(symbol)
    print(f"Актив: {data['symbol']}, Цена: ${data['price']}, RSI 1h: {data['rsi_1h']}")
    
    clean_bot = bot_username.lstrip("@")
    bot_tag = f"@{clean_bot}"
    chan_str = f"Канал: {channel_tag}" if not channel_tag.startswith("Канал:") else channel_tag
    
    voice_text = (
        f"Внимание по активу {data['symbol']}! Наш автосканер обнаружил новую формацию на часовом графике. "
        f"Цена {int(data['price'])} долларов. Индикатор RSI на отметке {int(data['rsi_1h'])}, "
        f"формируя вердикт: {data['verdict']}. "
        f"Забирай бесплатного бота-сканера в Телеграм: собака {clean_bot.replace('_', ' ')}. "
        f"Ссылка закреплена в профиле!"
    )
    
    audio_path = os.path.join(VIDEOS_DIR, f"temp_voice_{symbol}.mp3")
    print("🎙 Генерируем дикторскую озвучку...")
    tts = gTTS(voice_text, lang="ru")
    tts.save(audio_path)
    
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    audio_dur = get_audio_duration(audio_path, ffmpeg_exe)
    total_duration = math.ceil(audio_dur + 0.5)
    total_frames = int(total_duration * FPS)
    print(f"Длительность звука: {audio_dur:.2f} сек. Всего кадров видео: {total_frames}")
    
    output_mp4 = os.path.join(VIDEOS_DIR, output_filename)
    
    cmd = [
        ffmpeg_exe,
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-pix_fmt", "rgb24",
        "-r", str(FPS),
        "-i", "-",
        "-i", audio_path,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        output_mp4
    ]
    
    print("🎬 Рендерим кадры и кодируем видео...")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    for frame_idx in range(total_frames):
        t = frame_idx / FPS
        frame_img = draw_frame(data, t, total_duration, bot_tag=bot_tag, channel_tag=chan_str)
        proc.stdin.write(frame_img.tobytes())
        
        if frame_idx % 30 == 0 or frame_idx == total_frames - 1:
            pct = int((frame_idx + 1) / total_frames * 100)
            sys.stdout.write(f"\rПрогресс: {pct}% ({frame_idx + 1}/{total_frames} кадров)")
            sys.stdout.flush()
            
    print("\nФинальная обработка видео...")
    proc.stdin.close()
    proc.wait()
    
    if os.path.exists(audio_path):
        os.remove(audio_path)
        
    print("=" * 60)
    print(f"🎉 ГОТОВО! Видео успешно создано:")
    print(f"Файл: {output_mp4}")
    print("=" * 60)
    return output_mp4

if __name__ == "__main__":
    asyncio.run(generate_reel())
