import asyncio
import os
import json
import urllib.request
import subprocess
from pathlib import Path
from dotenv import load_dotenv

import config
import tunnel_manager
import web_server

BASE_DIR = Path(__file__).parent.resolve()

def test_cloudflared_binary():
    print("\n--- 1. Testing cloudflared.exe binary ---")
    bin_path = BASE_DIR / "tools" / "cloudflared.exe"
    assert bin_path.exists(), f"cloudflared.exe not found at {bin_path}"
    res = subprocess.run([str(bin_path), "--version"], capture_output=True, text=True)
    assert res.returncode == 0, f"cloudflared --version failed: {res.stderr}"
    print(f"✅ cloudflared binary verified: {res.stdout.strip()} ({bin_path.stat().st_size} bytes)")

def test_bot_api_registration():
    print("\n--- 2. Testing Telegram Bot API endpoints ---")
    load_dotenv(BASE_DIR / ".env", override=True)
    token = os.getenv("BOT_TOKEN")
    assert token, "BOT_TOKEN not found in .env"

    # getMe
    url_me = f"https://api.telegram.org/bot{token}/getMe"
    with urllib.request.urlopen(url_me) as resp:
        me_res = json.loads(resp.read().decode("utf-8"))
        assert me_res.get("ok"), f"getMe failed: {me_res}"
        bot_user = me_res["result"]
        print(f"✅ Bot connected: @{bot_user.get('username')} (ID: {bot_user.get('id')})")

    # setChatMenuButton and getChatMenuButton
    test_url = "https://app.cryptoradar.pro"
    cfg_res = tunnel_manager.configure_telegram_bot(token, test_url)
    assert cfg_res.get("setChatMenuButton", {}).get("ok"), f"setChatMenuButton failed: {cfg_res}"
    assert cfg_res.get("setMyCommands", {}).get("ok"), f"setMyCommands failed: {cfg_res}"
    print("✅ setChatMenuButton and setMyCommands returned ok: True")

    # Verify getChatMenuButton
    url_get_menu = f"https://api.telegram.org/bot{token}/getChatMenuButton"
    with urllib.request.urlopen(url_get_menu) as resp:
        menu_res = json.loads(resp.read().decode("utf-8"))
        assert menu_res.get("ok")
        btn = menu_res["result"]
        assert btn.get("type") == "web_app", f"Expected type web_app, got {btn}"
        assert btn.get("text") == "🚀 Терминал PRO", f"Expected '🚀 Терминал PRO', got {btn}"
        print(f"✅ getChatMenuButton verified: text='{btn.get('text')}', url='{btn.get('web_app', {}).get('url')}'")

    # Verify getMyCommands
    url_get_cmds = f"https://api.telegram.org/bot{token}/getMyCommands"
    with urllib.request.urlopen(url_get_cmds) as resp:
        cmds_res = json.loads(resp.read().decode("utf-8"))
        assert cmds_res.get("ok")
        cmds = {c["command"]: c["description"] for c in cmds_res["result"]}
        assert "start" in cmds
        assert "signals" in cmds
        assert "vip" in cmds
        assert "partner" in cmds
        assert "help" in cmds
        print(f"✅ getMyCommands verified: {len(cmds)} commands registered ({list(cmds.keys())})")

async def test_server_and_tunnel_manager():
    print("\n--- 3. Testing TunnelManager & Web Server Integration ---")
    runner = await web_server.start_web_server("127.0.0.1", 8080)
    try:
        mgr = tunnel_manager.TunnelManager(port=8080, host="127.0.0.1")
        assert mgr.is_port_open(), "Port 8080 should be open"
        print("✅ Local web server confirmed listening on port 8080")
        
        # Test tunnel acquisition
        live_url = mgr.start_tunnel()
        assert live_url.startswith("https://"), f"Expected https URL, got {live_url}"
        print(f"✅ Active Tunnel URL obtained: {live_url} via {mgr.provider_name}")

        # Update Bot API with live URL
        load_dotenv(BASE_DIR / ".env", override=True)
        token = os.getenv("BOT_TOKEN")
        final_res = tunnel_manager.configure_telegram_bot(token, live_url)
        assert final_res["setChatMenuButton"]["ok"]
        print(f"✅ Live WebApp menu button configured to: {live_url}")

        mgr.stop_tunnel()
    finally:
        await runner.cleanup()
        print("✅ Local test server stopped.")

def main():
    print("=" * 65)
    print("🧪 AUTOMATED VERIFICATION SUITE: TUNNEL & TELEGRAM BOT API")
    print("=" * 65)

    test_cloudflared_binary()
    test_bot_api_registration()
    asyncio.run(test_server_and_tunnel_manager())

    print("\n" + "=" * 65)
    print("🎉 ALL TESTS PASSED SUCCESSFULLY! 100% READY FOR PRODUCTION.")
    print("=" * 65)

if __name__ == "__main__":
    main()
