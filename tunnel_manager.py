import os
import sys
import re
import time
import json
import atexit
import logging
import signal
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("TunnelManager")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

BASE_DIR = Path(__file__).parent.resolve()
ENV_FILE = BASE_DIR / ".env"
CLOUDFLARED_BIN = BASE_DIR / "tools" / "cloudflared.exe"

class TunnelManager:
    def __init__(self, port: int = 8080, host: str = "127.0.0.1"):
        self.port = port
        self.host = host
        self.process: Optional[subprocess.Popen] = None
        self.active_url: Optional[str] = None
        self.provider_name: Optional[str] = None
        atexit.register(self.stop_tunnel)

    def is_port_open(self) -> bool:
        """Проверяет, отвечает ли локальный веб-сервер на указанном порту."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((self.host, self.port)) == 0

    def start_tunnel(self, timeout_sec: int = 15) -> str:
        """Запускает туннель (приоритет: Cloudflare -> Tunnelmole -> Localtunnel)."""
        logger.info(f"🚀 Инициализация HTTPS туннеля для локального порта {self.port}...")

        # 1. Попытка запустить Cloudflare Tunnel
        url = self._try_cloudflared(timeout_sec=6)
        if url:
            self.active_url = url
            self.provider_name = "Cloudflare Tunnel"
            logger.info(f"✅ Cloudflare HTTPS туннель активен: {url}")
            return url

        logger.warning("⚠️ Cloudflare Tunnel недоступен или заблокирован провайдером. Переключение на надежный резервный шлюз (Tunnelmole)...")

        # 2. Надежный fallback: Tunnelmole (чистый HTTPS без баннеров/паролей)
        url = self._try_tunnelmole(timeout_sec=12)
        if url:
            self.active_url = url
            self.provider_name = "Tunnelmole"
            logger.info(f"✅ Tunnelmole HTTPS туннель активен: {url}")
            return url

        # 3. Дополнительный fallback: Localtunnel
        logger.warning("⚠️ Попытка запуска Localtunnel шлюза...")
        url = self._try_localtunnel(timeout_sec=10)
        if url:
            self.active_url = url
            self.provider_name = "Localtunnel"
            logger.info(f"✅ Localtunnel HTTPS туннель активен: {url}")
            return url

        raise RuntimeError("Не удалось запустить ни один из публичных HTTPS туннелей. Проверьте интернет-соединение.")

    def _try_cloudflared(self, timeout_sec: int = 6) -> Optional[str]:
        bin_path = None
        if CLOUDFLARED_BIN.exists():
            bin_path = str(CLOUDFLARED_BIN)
        else:
            # Поиск в PATH или Program Files
            common_paths = [
                Path("C:/Program Files (x86)/cloudflared/cloudflared.exe"),
                Path("C:/Program Files/cloudflared/cloudflared.exe"),
            ]
            for p in common_paths:
                if p.exists():
                    bin_path = str(p)
                    break

        if not bin_path:
            logger.info("Бинарник cloudflared.exe не найден.")
            return None

        cmd = [bin_path, "tunnel", "--url", f"http://{self.host}:{self.port}"]
        try:
            logger.info(f"Запуск cloudflared: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            start_time = time.time()
            while time.time() - start_time < timeout_sec:
                if proc.poll() is not None:
                    # Процесс завершился с ошибкой
                    break
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                # Исключаем служебный эндпоинт api.trycloudflare.com
                match = re.search(r"https://(?!api\b)[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if match:
                    self.process = proc
                    return match.group(0)

            # Если URL не получен вовремя или процесс упал
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return None
        except Exception as e:
            logger.warning(f"Ошибка при запуске cloudflared: {e}")
            return None

    def _try_tunnelmole(self, timeout_sec: int = 12) -> Optional[str]:
        # В Windows используем npx.cmd
        npx_bin = "npx.cmd" if sys.platform == "win32" else "npx"
        cmd = [npx_bin, "--yes", "tunnelmole", str(self.port)]
        try:
            logger.info(f"Запуск tunnelmole: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            start_time = time.time()
            while time.time() - start_time < timeout_sec:
                if proc.poll() is not None:
                    break
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                match = re.search(r"https://[a-zA-Z0-9-]+\.(?:tunnelmole\.net|tunnelmole\.com)", line)
                if match:
                    self.process = proc
                    return match.group(0)

            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return None
        except Exception as e:
            logger.warning(f"Ошибка при запуске tunnelmole: {e}")
            return None

    def _try_localtunnel(self, timeout_sec: int = 10) -> Optional[str]:
        npx_bin = "npx.cmd" if sys.platform == "win32" else "npx"
        cmd = [npx_bin, "--yes", "localtunnel", "--port", str(self.port)]
        try:
            logger.info(f"Запуск localtunnel: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            start_time = time.time()
            while time.time() - start_time < timeout_sec:
                if proc.poll() is not None:
                    break
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                match = re.search(r"https://[a-zA-Z0-9-]+\.loca\.lt", line)
                if match:
                    self.process = proc
                    return match.group(0)

            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return None
        except Exception as e:
            logger.warning(f"Ошибка при запуске localtunnel: {e}")
            return None

    def stop_tunnel(self):
        """Останавливает запущенный туннель."""
        if self.process and self.process.poll() is None:
            logger.info("Остановка процесса туннеля...")
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

def update_env_file(webapp_url: str, web_host: str = "0.0.0.0", web_port: int = 8080) -> bool:
    """Обновляет или добавляет WEBAPP_URL, WEB_HOST, WEB_PORT в файле .env."""
    if not ENV_FILE.exists():
        logger.warning(f"Файл {ENV_FILE} не найден.")
        return False

    try:
        content = ENV_FILE.read_text(encoding="utf-8")
        lines = content.splitlines()
        
        updated_keys = {"WEBAPP_URL": False, "WEB_HOST": False, "WEB_PORT": False}
        new_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("WEBAPP_URL="):
                new_lines.append(f"WEBAPP_URL={webapp_url}")
                updated_keys["WEBAPP_URL"] = True
            elif stripped.startswith("WEB_HOST="):
                new_lines.append(f"WEB_HOST={web_host}")
                updated_keys["WEB_HOST"] = True
            elif stripped.startswith("WEB_PORT="):
                new_lines.append(f"WEB_PORT={web_port}")
                updated_keys["WEB_PORT"] = True
            else:
                new_lines.append(line)

        # Дописываем ключи, если их не было в файле
        if not updated_keys["WEB_HOST"]:
            new_lines.append(f"WEB_HOST={web_host}")
        if not updated_keys["WEB_PORT"]:
            new_lines.append(f"WEB_PORT={web_port}")
        if not updated_keys["WEBAPP_URL"]:
            new_lines.append(f"WEBAPP_URL={webapp_url}")

        new_content = "\n".join(new_lines) + "\n"
        ENV_FILE.write_text(new_content, encoding="utf-8")
        logger.info(f"✅ Файл .env успешно обновлен: WEBAPP_URL={webapp_url}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка обновления .env: {e}")
        return False

def configure_telegram_bot(bot_token: str, webapp_url: str) -> Dict[str, Any]:
    """
    Настраивает Telegram-бота через Bot API:
    1. Устанавливает WebApp кнопку меню (setChatMenuButton): "🚀 Терминал PRO"
    2. Регистрирует официальные команды бота (setMyCommands):
       /start, /signals, /vip, /partner, /help
    """
    if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("❌ Не указан действительный BOT_TOKEN.")
        return {"ok": False, "error": "Invalid BOT_TOKEN"}

    results = {}

    # 1. setChatMenuButton
    menu_button_payload = {
        "menu_button": {
            "type": "web_app",
            "text": "🚀 Терминал PRO",
            "web_app": {
                "url": webapp_url
            }
        }
    }
    url_menu = f"https://api.telegram.org/bot{bot_token}/setChatMenuButton"
    try:
        data = json.dumps(menu_button_payload).encode("utf-8")
        req = urllib.request.Request(url_menu, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            results["setChatMenuButton"] = res
            if res.get("ok"):
                logger.info("✅ Telegram Bot API: WebApp кнопка меню ('🚀 Терминал PRO') успешно установлена!")
            else:
                logger.warning(f"⚠️ Telegram Bot API setChatMenuButton вернул: {res}")
    except Exception as e:
        logger.error(f"❌ Ошибка вызова setChatMenuButton: {e}")
        results["setChatMenuButton"] = {"ok": False, "error": str(e)}

    # 2. setMyCommands
    commands_payload = {
        "commands": [
            {"command": "start", "description": "🚀 Запустить терминал и радар"},
            {"command": "signals", "description": "📊 AI торговые сигналы"},
            {"command": "vip", "description": "💎 Тарифы и VIP доступ"},
            {"command": "partner", "description": "🤝 Партнерская программа (30% Rev-Share)"},
            {"command": "help", "description": "ℹ️ Помощь и поддержка"}
        ]
    }
    url_commands = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
    try:
        data = json.dumps(commands_payload).encode("utf-8")
        req = urllib.request.Request(url_commands, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            results["setMyCommands"] = res
            if res.get("ok"):
                logger.info("✅ Telegram Bot API: Список официальных команд (/start, /signals, /vip, /partner, /help) успешно зарегистрирован!")
            else:
                logger.warning(f"⚠️ Telegram Bot API setMyCommands вернул: {res}")
    except Exception as e:
        logger.error(f"❌ Ошибка вызова setMyCommands: {e}")
        results["setMyCommands"] = {"ok": False, "error": str(e)}

    return results

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)
    token = os.getenv("BOT_TOKEN", "").strip()

    print("=" * 60)
    print("🛠️ Запуск автономной настройки Telegram Bot API & Туннеля")
    print("=" * 60)

    mgr = TunnelManager(port=8080)
    try:
        # Проверяем порт
        if not mgr.is_port_open():
            print("⚠️ Локальный веб-сервер на порту 8080 сейчас не запущен.")
            print("Для постоянного туннеля запустите python start_saas.py или run.bat.")
        else:
            print("✅ Обнаружен активный веб-сервер на порту 8080.")
            url = mgr.start_tunnel()
            print(f"🌐 Активный HTTPS URL: {url}")
            update_env_file(url)
            if token:
                res = configure_telegram_bot(token, url)
                print(f"Результат настройки Bot API: {res}")
    finally:
        mgr.stop_tunnel()
