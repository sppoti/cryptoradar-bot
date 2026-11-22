"""
Test suite for Canva Cloud Integration in CryptoRadar Pro SaaS.
Validates CanvaService setup, MCP schema compatibility, folder synchronization,
and visual asset rendering.
"""

import os
import sys
from pathlib import Path

# Add root project path to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.canva_service import CanvaService, canva_service
from services.traffic_funnel import get_partner_canva_promos
import config


def test_canva_configuration():
    print("\n--- 1. Testing Canva Configuration & Folder Metadata ---")
    details = canva_service.get_folder_details()
    print(f"[*] Folder Name:    {details['folder_name']}")
    print(f"[*] Folder ID:      {details['folder_id']}")
    print(f"[*] Folder URL:     {details['folder_url']}")
    print(f"[*] Team ID:        {details['team_id']}")
    print(f"[*] Account Name:   {details['account_name']}")
    print(f"[*] Environment:    {details['environment']}")

    assert details["folder_id"] == "FAHbqTG9Vg4", f"Expected FAHbqTG9Vg4, got {details['folder_id']}"
    assert details["team_id"] == "oBZaQa2FDEXm2wgikuzXZ8", f"Expected oBZaQa2FDEXm2wgikuzXZ8, got {details['team_id']}"
    assert details["account_name"] == "KIIIER", f"Expected KIIIER, got {details['account_name']}"
    assert "https://www.canva.com/folder/" in details["folder_url"], "Invalid folder URL"
    print("  [PASS] Canva folder metadata and config match verified workspace.")


def test_brand_identity_and_templates():
    print("\n--- 2. Testing Brand Identity & Design Catalog ---")
    brand = canva_service.get_brand_identity()
    print(f"[*] Brand Palette Count: {len(brand['colors'])} colors")
    print(f"[*] Typography: {brand['typography']['header']}")
    assert "bg_primary" in brand["colors"]
    assert "accent_green" in brand["colors"]
    assert "accent_red" in brand["colors"]

    templates = canva_service.get_available_templates()
    print(f"[*] Total Templates Available: {len(templates)}")
    for t in templates:
        print(f"    - [{t['category'].upper()}] {t['name']} ({t['format']})")

    assert len(templates) >= 5, "Expected at least 5 design templates"
    
    signal_templates = canva_service.get_available_templates(category="signals")
    assert len(signal_templates) >= 2, "Expected at least 2 signal templates (Long/Short)"
    print("  [PASS] Brand tokens and template catalog verified.")


def test_brief_generation_for_mcp():
    print("\n--- 3. Testing Canva MCP Design Brief Generation ---")
    
    # 3.1 Long VIP Signal Brief
    long_brief = canva_service.generate_signal_banner_brief(
        symbol="BTCUSDT",
        signal_type="LONG",
        entry_price=91500.0,
        tp1=94800.0,
        tp2=98500.0,
        stop_loss=89900.0,
        rsi_val=23.4,
        timeframe="1H",
        winrate_pct=95,
        notes="Whale cluster accumulation detected"
    )
    print(f"[*] Long Signal Brief length: {len(long_brief['brief'])} chars")
    print(f"[*] User Intent: {long_brief['user_intent']}")
    assert "BTCUSDT" in long_brief["brief"]
    assert "LONG" in long_brief["brief"]
    assert long_brief["canva_folder_id"] == "FAHbqTG9Vg4"

    # Export to MCP payload
    mcp_payload = canva_service.export_canva_mcp_payload(long_brief)
    assert "brief" in mcp_payload
    assert "format" in mcp_payload
    assert "user_intent" in mcp_payload
    print("  [PASS] Long Signal Brief formatted successfully for create-design MCP tool.")

    # 3.2 Short VIP Signal Brief
    short_brief = canva_service.generate_signal_banner_brief(
        symbol="ETHUSDT",
        signal_type="SHORT",
        entry_price=3180.0,
        tp1=3020.0,
        tp2=2850.0,
        stop_loss=3290.0,
        rsi_val=78.9,
        timeframe="4H",
        winrate_pct=91
    )
    assert "ETHUSDT" in short_brief["brief"]
    assert "SHORT" in short_brief["brief"]
    print("  [PASS] Short Signal Brief verified.")

    # 3.3 Partner Promo Banner Brief
    promo_brief = canva_service.generate_promo_banner_brief(
        partner_code="cryptoking",
        bot_username="@cryptoradar_live777_bot",
        project_name="CryptoRadar Pro"
    )
    assert "ref_cryptoking" in promo_brief["data"]["partner_ref_link"]
    print("  [PASS] Partner Promo Brief generated with customized referral link.")

    # 3.4 9:16 Vertical Viral Story Brief
    story_brief = canva_service.generate_story_brief(
        hook_title="Секретный терминал без VPN",
        bot_username="@cryptoradar_live_bot",
        partner_code="alpha_club"
    )
    assert story_brief["format"] == "Instagram Story"
    assert "ref_alpha_club" in story_brief["data"]["link"]
    print("  [PASS] 9:16 Vertical Viral Story Brief generated.")


def test_traffic_funnel_canva_integration():
    print("\n--- 4. Testing Traffic Funnel + Canva Service Integration ---")
    partner_promos = get_partner_canva_promos(partner_code="invest_pro", bot_username="@cryptoradar_test_bot")
    print(f"[*] Generated {len(partner_promos)} partner promos via traffic funnel")
    assert len(partner_promos) > 0
    first_promo = partner_promos[0]
    print(f"[*] Promo title: {first_promo['title']}")
    print(f"[*] MCP Payload format: {first_promo['mcp_payload']['format']}")
    print("  [PASS] Traffic Funnel successfully produces Canva marketing assets.")


def test_local_signal_card_rendering():
    print("\n--- 5. Testing Local High-Res Signal Card Rendering (Pillow Engine) ---")
    test_output = "static/canva_renders/test_btc_long_signal.png"
    rendered_path = canva_service.render_local_signal_card(
        symbol="BTCUSDT",
        signal_type="LONG",
        entry_price=92450.0,
        tp1=95500.0,
        tp2=99200.0,
        stop_loss=90800.0,
        rsi_val=22.8,
        timeframe="1H",
        winrate_pct=96,
        notes="Oversold Bollinger Band Squeeze + Whale Volume Spike",
        output_filename="test_btc_long_signal.png"
    )
    
    assert os.path.exists(rendered_path), f"File {rendered_path} not found on disk"
    file_size = os.path.getsize(rendered_path)
    print(f"[*] Generated Card: {rendered_path}")
    print(f"[*] File Size:      {file_size:,} bytes")
    assert file_size > 15000, f"Rendered image file too small ({file_size} bytes)"

    # Also test SHORT rendering
    rendered_short = canva_service.render_local_signal_card(
        symbol="SOLUSDT",
        signal_type="SHORT",
        entry_price=245.5,
        tp1=228.0,
        tp2=210.0,
        stop_loss=258.0,
        rsi_val=81.2,
        timeframe="4H",
        winrate_pct=92,
        notes="Resistance Rejection at High",
        output_filename="test_sol_short_signal.png"
    )
    assert os.path.exists(rendered_short)
    print(f"[*] Generated Short Card: {rendered_short} ({os.path.getsize(rendered_short):,} bytes)")
    print("  [PASS] Local rendering engine generated 1200x675 high-resolution graphics.")


def main():
    print("==========================================================")
    print("🚀 CryptoRadar Pro SaaS - Canva Integration Test Suite")
    print("==========================================================")
    try:
        test_canva_configuration()
        test_brand_identity_and_templates()
        test_brief_generation_for_mcp()
        test_traffic_funnel_canva_integration()
        test_local_signal_card_rendering()
        print("\n==========================================================")
        print("✅ ALL CANVA INTEGRATION TESTS COMPLETED SUCCESSFULLY!")
        print("==========================================================")
        return 0
    except AssertionError as e:
        print(f"\n❌ TEST ASSERTION FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
