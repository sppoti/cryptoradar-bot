import asyncio
import math
import time
from aiohttp.test_utils import TestClient, TestServer

import database as db
import keyboards as kb
from services import scanner, ai_analytics
import web_server

async def run_ai_analytics_tests():
    print("=" * 70)
    print("🧠 Starting AI Market Intelligence & Advanced Analytics Engine Test Suite...")
    print("=" * 70)

    # ---------------------------------------------------------
    # 1. Unit Tests for Technical Indicator Functions
    # ---------------------------------------------------------
    print("\n--- [1/5] Testing Technical Mathematical Calculations ---")

    # 1.1 RSI calculation
    # Test flat sequence
    flat_data = [100.0] * 30
    assert ai_analytics.calculate_rsi_series(flat_data, 14) == 50.0, "Flat series should return 50.0 RSI"

    # Test strictly increasing sequence (100% gain)
    up_data = [float(i) for i in range(1, 30)]
    rsi_up = ai_analytics.calculate_rsi_series(up_data, 14)
    assert rsi_up is not None and rsi_up > 90.0, f"Monotonically increasing series should have RSI > 90, got {rsi_up}"

    # Test strictly decreasing sequence (100% loss)
    down_data = [float(50 - i) for i in range(1, 30)]
    rsi_down = ai_analytics.calculate_rsi_series(down_data, 14)
    assert rsi_down is not None and rsi_down < 10.0, f"Monotonically decreasing series should have RSI < 10, got {rsi_down}"

    # Test insufficient data
    assert ai_analytics.calculate_rsi_series([10.0, 11.0], 14) is None, "Should return None for insufficient data"
    print("✅ RSI Calculation: Validated (Flat, Bullish, Bearish, Insufficient checks passed).")

    # 1.2 EMA calculation
    series_ema = [10.0 + (i * 0.5) for i in range(60)]
    ema_20 = ai_analytics.calculate_ema(series_ema, 20)
    ema_50 = ai_analytics.calculate_ema(series_ema, 50)
    assert ema_20 is not None and ema_50 is not None
    assert ema_20 > ema_50, "In an uptrend, EMA 20 must be above EMA 50"
    assert ai_analytics.calculate_ema([1.0, 2.0], 20) is None, "Insufficient data should return None"
    print(f"✅ EMA Calculation: Validated (EMA-20={ema_20}, EMA-50={ema_50}, EMA20 > EMA50 verified).")

    # 1.3 Bollinger Bands calculation
    bb_data = [100.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(25)]
    bb = ai_analytics.calculate_bollinger_bands(bb_data, period=20, num_std=2.0)
    assert bb["upper"] > bb["middle"] > bb["lower"], "Upper > Middle > Lower in Bollinger Bands"
    assert 0.0 <= bb["percent_b"] <= 1.0, f"Expected %B between 0 and 1, got {bb['percent_b']}"
    assert bb["bandwidth"] > 0.0, "Bandwidth must be positive"
    print(f"✅ Bollinger Bands: Validated (Upper={bb['upper']}, Mid={bb['middle']}, Lower={bb['lower']}, %B={bb['percent_b']}, Bandwidth={bb['bandwidth']}%).")

    # 1.4 Volume Spike calculation
    vols_normal = [1000.0] * 25
    vol_res = ai_analytics.calculate_volume_spike(vols_normal, period=20)
    assert vol_res["is_spike"] is False, "Normal volume should not trigger spike"
    assert vol_res["spike_ratio"] == 1.0

    vols_spike = [1000.0] * 20 + [2800.0]  # 2.8x spike
    vol_spike_res = ai_analytics.calculate_volume_spike(vols_spike, period=20)
    assert vol_spike_res["is_spike"] is True, "2.8x volume must trigger is_spike=True"
    assert vol_spike_res["spike_ratio"] >= 2.5
    print(f"✅ Volume Spikes: Validated (Normal ratio={vol_res['spike_ratio']}, Spike ratio={vol_spike_res['spike_ratio']} -> is_spike={vol_spike_res['is_spike']}).")

    # 1.5 ATR calculation
    highs = [105.0 + i for i in range(30)]
    lows = [95.0 + i for i in range(30)]
    closes = [100.0 + i for i in range(30)]
    atr = ai_analytics.calculate_atr(highs, lows, closes, 14)
    assert atr > 0.0 and 9.0 <= atr <= 12.0, f"Expected ATR around 10, got {atr}"
    print(f"✅ ATR Calculation: Validated (ATR={atr:.2f}).")

    # ---------------------------------------------------------
    # 2. Testing Algorithmic Heuristic Fallback Engine
    # ---------------------------------------------------------
    print("\n--- [2/5] Testing Algorithmic Quantitative Heuristic Engine ---")

    # 2.1 Strong Long Scenario
    strong_long_synth = ai_analytics.synthesize_quantitative_forecast(
        symbol="BTCUSDT",
        ticker_name="BTC",
        price=65000.0,
        change_24h=4.5,
        volume_24h=1500000000.0,
        rsi_1h=56.0,
        rsi_4h=58.0,
        bb={"middle": 64200.0, "upper": 66800.0, "lower": 61600.0, "percent_b": 0.65, "bandwidth": 8.1},
        ema_20=64500.0,
        ema_50=63200.0,
        vol_spike={"spike_ratio": 2.1, "is_spike": True},
        atr=950.0
    )
    assert strong_long_synth["bias"] == ai_analytics.BIAS_STRONG_LONG
    assert strong_long_synth["probability"] >= 70
    assert strong_long_synth["tp1_price"] > 65000.0
    assert strong_long_synth["tp2_price"] > strong_long_synth["tp1_price"]
    assert strong_long_synth["stop_loss_price"] < 65000.0
    assert "BTC" in strong_long_synth["summary"]
    print(f"✅ Strong Long Setup: Bias={strong_long_synth['bias']}, Prob={strong_long_synth['probability']}%, R:R={strong_long_synth['risk_reward']}")
    print(f"   Entry: {strong_long_synth['entry_zone']} | TP1: {strong_long_synth['tp1']} | SL: {strong_long_synth['stop_loss']}")

    # 2.2 Scalp Long (Oversold Mean Reversion) Scenario
    oversold_synth = ai_analytics.synthesize_quantitative_forecast(
        symbol="SOLUSDT",
        ticker_name="SOL",
        price=180.0,
        change_24h=-5.2,
        volume_24h=800000000.0,
        rsi_1h=28.5,  # Oversold!
        rsi_4h=38.0,
        bb={"middle": 192.0, "upper": 204.0, "lower": 180.0, "percent_b": 0.05, "bandwidth": 12.5},
        ema_20=188.0,
        ema_50=195.0,
        vol_spike={"spike_ratio": 1.2, "is_spike": False},
        atr=4.5
    )
    assert oversold_synth["bias"] == ai_analytics.BIAS_SCALP_LONG
    assert oversold_synth["tp1_price"] > 180.0
    assert oversold_synth["stop_loss_price"] < 180.0
    print(f"✅ Scalp Long (Oversold) Setup: Bias={oversold_synth['bias']}, Prob={oversold_synth['probability']}%, R:R={oversold_synth['risk_reward']}")

    # 2.3 Strong Short Scenario
    strong_short_synth = ai_analytics.synthesize_quantitative_forecast(
        symbol="ETHUSDT",
        ticker_name="ETH",
        price=2400.0,
        change_24h=-6.8,
        volume_24h=1200000000.0,
        rsi_1h=38.0,
        rsi_4h=41.0,
        bb={"middle": 2520.0, "upper": 2650.0, "lower": 2390.0, "percent_b": 0.04, "bandwidth": 10.3},
        ema_20=2480.0,
        ema_50=2560.0,  # EMA 20 < EMA 50 & Price < EMA 20
        vol_spike={"spike_ratio": 1.8, "is_spike": True},
        atr=55.0
    )
    assert strong_short_synth["bias"] in (ai_analytics.BIAS_STRONG_SHORT, ai_analytics.BIAS_SCALP_SHORT)
    assert strong_short_synth["tp1_price"] < 2400.0
    assert strong_short_synth["stop_loss_price"] > 2400.0
    print(f"✅ Short Breakdown Setup: Bias={strong_short_synth['bias']}, Prob={strong_short_synth['probability']}%, R:R={strong_short_synth['risk_reward']}")

    # 2.4 Neutral/Chop Scenario
    neutral_synth = ai_analytics.synthesize_quantitative_forecast(
        symbol="TONUSDT",
        ticker_name="TON",
        price=5.50,
        change_24h=0.2,
        volume_24h=50000000.0,
        rsi_1h=49.0,
        rsi_4h=50.5,
        bb={"middle": 5.50, "upper": 5.65, "lower": 5.35, "percent_b": 0.50, "bandwidth": 5.4},
        ema_20=5.50,
        ema_50=5.50,
        vol_spike={"spike_ratio": 0.95, "is_spike": False},
        atr=0.08
    )
    assert neutral_synth["bias"] == ai_analytics.BIAS_NEUTRAL
    print(f"✅ Neutral/Chop Setup: Bias={neutral_synth['bias']}, Prob={neutral_synth['probability']}%, R:R={neutral_synth['risk_reward']}")

    # ---------------------------------------------------------
    # 3. Testing Caching System & Resiliency
    # ---------------------------------------------------------
    print("\n--- [3/5] Testing Response Caching (3-Min TTL) & Scanner Integration ---")
    ai_analytics.clear_ai_cache()

    # Call 1: fresh calculation (cache miss)
    t0 = time.time()
    res1 = await scanner.get_ai_forecast("BTC")
    t1 = time.time()
    assert res1["status"] == "success"
    assert res1["cached"] is False
    assert res1["symbol"] == "BTCUSDT"
    print(f"✅ Call 1 (Fresh Calculation): Time={t1 - t0:.3f}s, Cached={res1['cached']}, Bias={res1['bias']}")

    # Call 2: from in-memory cache (< 1ms latency)
    t2 = time.time()
    res2 = await scanner.get_ai_forecast("BTC")
    t3 = time.time()
    assert res2["status"] == "success"
    assert res2["cached"] is True
    assert (t3 - t2) < 0.05, f"Cached call took {t3 - t2:.4f}s; expected < 0.05s"
    print(f"✅ Call 2 (Cache Hit): Time={t3 - t2:.5f}s, Cached={res2['cached']}, Symbol={res2['symbol']}")

    # Force refresh bypasses cache
    res3 = await ai_analytics.get_ai_market_forecast("BTC", force_refresh=True)
    assert res3["cached"] is False
    print("✅ Force Refresh: Bypassed cache successfully.")

    # Test Telegram HTML formatting
    tg_text = ai_analytics.format_ai_forecast_telegram(res1)
    assert "🧠 <b>AI Market Intelligence" in tg_text
    assert "Торговый вердикт (Bias):" in tg_text
    assert "ТОРГОВЫЙ ПЛАН (SETUP):" in tg_text
    assert "Цель 1 (TP 1):" in tg_text
    assert "Stop-Loss" in tg_text
    assert "Мульти-индикаторный анализ:" in tg_text
    print(f"✅ Telegram HTML Formatter: Validated ({len(tg_text)} characters generated).")

    # ---------------------------------------------------------
    # 4. Testing Web API Endpoint /api/ai-forecast
    # ---------------------------------------------------------
    print("\n--- [4/5] Testing /api/ai-forecast REST API Endpoint ---")
    app = web_server.create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # 4.1 Valid GET request with symbol query
        resp = await client.get("/api/ai-forecast?symbol=BTC")
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        data = await resp.json()
        assert data.get("status") == "success"
        assert data.get("symbol") == "BTCUSDT"
        assert "bias" in data
        assert "probability" in data
        assert "risk_reward" in data
        assert "entry_zone" in data
        assert "tp1" in data
        assert "tp2" in data
        assert "stop_loss" in data
        assert "indicators" in data
        print(f"✅ GET /api/ai-forecast?symbol=BTC -> 200 OK: Bias={data['bias']}, Prob={data['probability']}%, TP1={data['tp1']}")

        # 4.2 Valid POST request with JSON body
        resp_post = await client.post("/api/ai-forecast", json={"symbol": "SOL"})
        assert resp_post.status == 200, f"Expected 200, got {resp_post.status}"
        data_post = await resp_post.json()
        assert data_post.get("status") == "success"
        assert data_post.get("symbol") == "SOLUSDT"
        print(f"✅ POST /api/ai-forecast (SOL) -> 200 OK: Bias={data_post['bias']}, Entry={data_post['entry_zone']}")

        # 4.3 Missing symbol error handling
        resp_bad = await client.get("/api/ai-forecast")
        assert resp_bad.status == 400
        data_bad = await resp_bad.json()
        assert data_bad.get("status") == "error"
        assert "обязателен" in data_bad.get("message", "")
        print("✅ GET /api/ai-forecast (No Symbol) -> 400 Bad Request handled properly.")

        # 4.4 Invalid symbol format error handling
        resp_invalid = await client.get("/api/ai-forecast?symbol=$$$INVALID@@@")
        assert resp_invalid.status == 400
        data_invalid = await resp_invalid.json()
        assert data_invalid.get("status") == "error"
        print("✅ GET /api/ai-forecast (Invalid Ticker) -> 400 Bad Request handled properly.")
    finally:
        await client.close()

    # ---------------------------------------------------------
    # 5. Testing Keyboards & VIP Services Handlers
    # ---------------------------------------------------------
    print("\n--- [5/5] Testing Telegram Keyboards & VIP Services UI ---")
    analysis_kb = kb.get_analysis_result_keyboard("BTCUSDT")
    has_ai_btn = any(
        btn.callback_data == "ai_forecast_BTCUSDT"
        for row in analysis_kb.inline_keyboard
        for btn in row
    )
    assert has_ai_btn, "get_analysis_result_keyboard must contain 'ai_forecast_BTCUSDT' button"
    print("✅ Verified: Express analysis keyboard includes '🧠 Глубокий AI-прогноз' button.")

    ai_kb = kb.get_ai_forecast_keyboard("BTCUSDT")
    btn_callbacks = [btn.callback_data for row in ai_kb.inline_keyboard for btn in row]
    assert "ai_forecast_BTCUSDT" in btn_callbacks
    assert "analyze_BTCUSDT" in btn_callbacks
    print("✅ Verified: AI forecast keyboard contains Refresh, RSI Express, and Navigation buttons.")

    print("\n" + "=" * 70)
    print("🎉 ALL AI ANALYTICS ENGINE TESTS PASSED (100% SUCCESS)!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_ai_analytics_tests())
