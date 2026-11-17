import asyncio
import sys
from aiohttp.test_utils import TestClient, TestServer
import database as db
import keyboards as kb
from aiogram.types import WebAppInfo
import web_server

async def run_tests():
    print("=" * 60)
    print("🚀 Starting TMA WebApp & Web API Verification Suite...")
    print("=" * 60)

    # 1. Initialize DB
    await db.init_db()
    print("✅ Database initialized successfully.")

    # 2. Test Keyboards
    main_menu = kb.get_main_menu(is_admin=False)
    webapp_kb = kb.get_webapp_keyboard()

    # Verify WebAppInfo in main_menu
    has_webapp_in_main = any(
        btn.web_app is not None and isinstance(btn.web_app, WebAppInfo)
        for row in main_menu.inline_keyboard
        for btn in row
    )
    assert has_webapp_in_main, "Main menu must contain a WebAppInfo button"
    print("✅ Verified: Main menu contains WebAppInfo TMA button.")

    # Verify WebAppInfo in webapp_kb
    has_webapp_in_dedicated = any(
        btn.web_app is not None and isinstance(btn.web_app, WebAppInfo)
        for row in webapp_kb.inline_keyboard
        for btn in row
    )
    assert has_webapp_in_dedicated, "Dedicated webapp keyboard must contain WebAppInfo button"
    print("✅ Verified: Dedicated WebApp keyboard contains WebAppInfo button.")

    # 3. Test Web Server Endpoints using aiohttp TestClient
    app = web_server.create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # Test /health
        resp = await client.get("/health")
        assert resp.status == 200, f"/health returned status {resp.status}"
        data = await resp.json()
        assert data.get("status") == "ok", f"Expected status ok, got {data}"
        print(f"✅ Verified: GET /health -> status 200: {data['service']}")

        # Test GET / (index.html)
        resp = await client.get("/")
        assert resp.status == 200, f"/ returned status {resp.status}"
        html_text = await resp.text()
        assert "<!DOCTYPE html>" in html_text
        assert "CryptoRadar PRO" in html_text
        assert "telegram-web-app.js" in html_text
        assert "tv_chart_container" in html_text
        print(f"✅ Verified: GET / (index.html) -> status 200, size {len(html_text)} bytes")

        # Test GET /style.css
        resp = await client.get("/style.css")
        assert resp.status == 200, f"/style.css returned status {resp.status}"
        css_text = await resp.text()
        assert "glass-card" in css_text
        assert "--accent-cyan" in css_text
        print(f"✅ Verified: GET /style.css -> status 200, size {len(css_text)} bytes")

        # Test GET /app.js
        resp = await client.get("/app.js")
        assert resp.status == 200, f"/app.js returned status {resp.status}"
        js_text = await resp.text()
        assert "Telegram" in js_text
        assert "TradingView" in js_text
        print(f"✅ Verified: GET /app.js -> status 200, size {len(js_text)} bytes")

        # Test GET /api/market-overview
        resp = await client.get("/api/market-overview")
        assert resp.status == 200, f"/api/market-overview returned status {resp.status}"
        market_json = await resp.json()
        assert market_json.get("status") == "success"
        assert "global" in market_json
        assert "tickers" in market_json
        assert len(market_json["tickers"]) > 0
        btc = market_json["tickers"][0]
        print(f"✅ Verified: GET /api/market-overview -> {len(market_json['tickers'])} tickers loaded. Example: {btc['ticker']} at {btc['price_formatted']} (24h: {btc['change_24h']}%)")

        # Test GET /api/signals
        resp = await client.get("/api/signals")
        assert resp.status == 200, f"/api/signals returned status {resp.status}"
        signals_json = await resp.json()
        assert signals_json.get("status") == "success"
        assert len(signals_json["signals"]) >= 3
        vip_signals = [s for s in signals_json["signals"] if s.get("is_vip")]
        free_signals = [s for s in signals_json["signals"] if not s.get("is_vip")]
        print(f"✅ Verified: GET /api/signals -> {len(signals_json['signals'])} signals loaded ({len(free_signals)} Free, {len(vip_signals)} VIP Locked)")

        # Test GET /api/tariffs
        resp = await client.get("/api/tariffs")
        assert resp.status == 200, f"/api/tariffs returned status {resp.status}"
        tariffs_json = await resp.json()
        assert tariffs_json.get("status") == "success"
        assert len(tariffs_json["tariffs"]) == 3
        print(f"✅ Verified: GET /api/tariffs -> {len(tariffs_json['tariffs'])} tariffs loaded: {[t['key'] for t in tariffs_json['tariffs']]}")

        # Test GET /api/user-status (Guest and Existing User)
        resp = await client.get("/api/user-status")
        guest_json = await resp.json()
        assert guest_json.get("user", {}).get("is_guest") is True
        print(f"✅ Verified: GET /api/user-status (guest) -> is_guest={guest_json['user']['is_guest']}")

        # Create dummy user in DB and test
        await db.get_or_create_user(999888, "test_tma_user", "TestTrader")
        resp = await client.get("/api/user-status?user_id=999888")
        user_json = await resp.json()
        assert user_json.get("user", {}).get("user_id") == 999888
        assert user_json.get("user", {}).get("first_name") == "TestTrader"
        print(f"✅ Verified: GET /api/user-status?user_id=999888 -> user found, VIP={user_json['user']['is_vip']}")

        print("=" * 60)
        print("🎉 ALL VERIFICATION CHECKS PASSED (100% SUCCESS)!")
        print("=" * 60)
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(run_tests())
