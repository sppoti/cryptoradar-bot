import os
import sys
import subprocess
import imageio_ffmpeg
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Добавляем ffmpeg в PATH
ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not API_KEY:
    print("=" * 60)
    print("❌ ОШИБКА: Не указан GEMINI_API_KEY в файле .env!")
    print("1. Получите бесплатный ключ на https://aistudio.google.com/")
    print("2. Вставьте его в c:\\TG\\.env: GEMINI_API_KEY=ваш_ключ")
    print("=" * 60)
    sys.exit(1)

# Путь к официальному скрипту генерации видео Gemini Omni 1.1 Flash
SKILL_SCRIPT = r"C:\Users\vorob\.gemini\config\plugins\gemini-api\skills\gemini-omni-flash-api\scripts\video\generate_video.py"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "videos")
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "gemini_omni_bitcoin.mp4")

# Промпт для генерации кинематографичного вертикального ролика
PROMPT = (
    "A stunning 9:16 vertical cinematic shot of a glowing holographic Bitcoin floating "
    "above a high-tech trader workstation. Neon green and cyan candlestick charts pulsing "
    "with real-time financial data in the background, reflections on dark glass desk, cyber aesthetic. "
    "A sleek digital glowing badge overlay in the lower third reads '@ssddssa_bot'. "
    "Sound design: ambient futuristic synth music with subtle digital market chimes. No dialogue."
)

cmd = [
    sys.executable,
    SKILL_SCRIPT,
    PROMPT,
    "--aspect-ratio", "9:16",
    "--resolution", "1080p",
    "--output", OUTPUT_FILE
]

print("🚀 Запуск генерации видео через нейросеть Gemini Omni 1.1 Flash...")
print(f"Формат: 9:16 (1080p Full HD)")
print(f"Файл сохранится в: {OUTPUT_FILE}")
print("Генерация нейросетевого видео занимает от 1 до 3 минут. Ожидайте...")

result = subprocess.run(cmd, env=os.environ)

if result.returncode == 0:
    print("=" * 60)
    print("🎉 Кинематографичное видео от Gemini Omni Flash успешно создано!")
    print(f"Файл: {OUTPUT_FILE}")
    print("=" * 60)
else:
    print("Ошибка генерации. Проверьте правильность API ключа.")
