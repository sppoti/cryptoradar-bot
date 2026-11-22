"""
Live SaaS Analytics Sync to Notion Command Center.
Queries real-time commercial and platform statistics from SQLite database
and synchronizes metrics with the Notion SaaS Command Center page.

Supports:
- Live database queries (registered users, active VIPs, 24h/all-time revenue, partners, commissions).
- Notion REST API integration (via NOTION_TOKEN or internal integrations).
- Notion MCP Server integration payload generation for notion-update-page.
- Local snapshot caching (static/notion_sync_state.json) for dashboard widgets & TMA APIs.
- Standalone CLI execution: python -m services.notion_sync
- Async background task runner for periodic synchronization.
"""

import os
import sys
import json
import asyncio
import logging
import datetime
import argparse
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

import aiosqlite
import config
import database as db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("NotionSyncService")

# Default Command Center Page ID (CryptoRadar Pro SaaS — Command Center)
DEFAULT_PAGE_ID = getattr(config, "NOTION_PAGE_ID", "41086ecf3dff80e28640e5a0071f5453")
STATE_FILE_PATH = Path("static/notion_sync_state.json")


async def fetch_platform_metrics(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Query real-time SaaS platform statistics from the SQLite database.
    
    Returns:
        Dict containing total users, active VIP subs, 24h & all-time revenue (Stars & RUB),
        partner count, affiliate commissions, pending payout requests, and conversion rates.
    """
    path = db_path or db.DB_PATH
    if not os.path.exists(path):
        logger.warning(f"Database file not found at {path}. Returning empty metrics.")
        return {
            "total_users": 0,
            "active_subs": 0,
            "stars_revenue": 0,
            "rub_revenue": 0,
            "revenue_24h_stars": 0,
            "revenue_24h_rub": 0,
            "total_partners": 0,
            "affiliate_stars": 0,
            "affiliate_rub": 0,
            "pending_payout_count": 0,
            "pending_payout_stars": 0,
            "pending_payout_rub": 0,
            "conversion_rate": 0.0,
            "revenue_24h_usd": 0.0,
            "total_estimated_usd": 0.0,
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    async with aiosqlite.connect(path) as conn:
        now_iso = datetime.datetime.now().isoformat()

        # 1. Total Registered Users
        c_users = await conn.execute("SELECT COUNT(*) FROM users")
        total_users = (await c_users.fetchone())[0] or 0

        # 2. Active VIP Subscriptions
        c_subs = await conn.execute(
            "SELECT COUNT(*) FROM users WHERE sub_until IS NOT NULL AND sub_until > ?",
            (now_iso,)
        )
        active_subs = (await c_subs.fetchone())[0] or 0

        # 3. All-Time Revenue (Stars & RUB)
        c_rev_stars = await conn.execute(
            "SELECT SUM(amount) FROM payments WHERE status = 'approved' AND currency = 'XTR'"
        )
        stars_revenue = (await c_rev_stars.fetchone())[0] or 0

        c_rev_rub = await conn.execute(
            "SELECT SUM(amount) FROM payments WHERE status = 'approved' AND currency = 'RUB'"
        )
        rub_revenue = (await c_rev_rub.fetchone())[0] or 0

        # 4. 24-Hour Revenue (Stars & RUB)
        c_24h_stars = await conn.execute(
            "SELECT SUM(amount) FROM payments WHERE status = 'approved' AND currency = 'XTR' "
            "AND created_at > datetime('now', '-24 hours')"
        )
        revenue_24h_stars = (await c_24h_stars.fetchone())[0] or 0

        c_24h_rub = await conn.execute(
            "SELECT SUM(amount) FROM payments WHERE status = 'approved' AND currency = 'RUB' "
            "AND created_at > datetime('now', '-24 hours')"
        )
        revenue_24h_rub = (await c_24h_rub.fetchone())[0] or 0

        # 5. Registered B2B Partners
        c_partners = await conn.execute("SELECT COUNT(*) FROM partners WHERE is_active = 1")
        total_partners = (await c_partners.fetchone())[0] or 0

        # 6. Total Affiliate Commissions Accrued
        c_aff_stars = await conn.execute(
            "SELECT SUM(commission_amount) FROM affiliate_earnings WHERE currency = 'XTR'"
        )
        affiliate_stars = (await c_aff_stars.fetchone())[0] or 0

        c_aff_rub = await conn.execute(
            "SELECT SUM(commission_amount) FROM affiliate_earnings WHERE currency = 'RUB'"
        )
        affiliate_rub = (await c_aff_rub.fetchone())[0] or 0

        # 7. Pending Payout Requests
        c_pending = await conn.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN currency = 'XTR' THEN amount ELSE 0 END), "
            "SUM(CASE WHEN currency = 'RUB' THEN amount ELSE 0 END) "
            "FROM payout_requests WHERE status = 'pending'"
        )
        p_row = await c_pending.fetchone()
        pending_payout_count = p_row[0] or 0
        pending_payout_stars = p_row[1] or 0
        pending_payout_rub = p_row[2] or 0

    # Calculated Financial and Conversion Metrics
    conversion_rate = (active_subs / total_users * 100) if total_users > 0 else 0.0
    total_estimated_usd = (stars_revenue * 0.02) + (rub_revenue / 90.0)
    revenue_24h_usd = (revenue_24h_stars * 0.02) + (revenue_24h_rub / 90.0)
    timestamp_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
        "total_users": total_users,
        "active_subs": active_subs,
        "stars_revenue": stars_revenue,
        "rub_revenue": rub_revenue,
        "revenue_24h_stars": revenue_24h_stars,
        "revenue_24h_rub": revenue_24h_rub,
        "total_partners": total_partners,
        "affiliate_stars": affiliate_stars,
        "affiliate_rub": affiliate_rub,
        "pending_payout_count": pending_payout_count,
        "pending_payout_stars": pending_payout_stars,
        "pending_payout_rub": pending_payout_rub,
        "conversion_rate": round(conversion_rate, 2),
        "revenue_24h_usd": round(revenue_24h_usd, 2),
        "total_estimated_usd": round(total_estimated_usd, 2),
        "timestamp_utc": timestamp_utc,
    }


def format_notion_callout_markdown(metrics: Dict[str, Any]) -> str:
    """
    Format metrics as a Notion-flavored Markdown callout block.
    Matches the official Notion Command Center layout structure.
    """
    return (
        f'<callout icon="⚡" color="green_bg">\n'
        f'<b>Live Platform Metrics & SaaS Telemetry (Auto-Synced)</b><br />\n'
        f'<b>Last Sync:</b> {metrics["timestamp_utc"]} | <b>Sync Engine:</b> services.notion_sync (Active)<br />\n'
        f'• <b>Total Registered Users:</b> {metrics["total_users"]} traders<br />\n'
        f'• <b>Active VIP Subscriptions:</b> {metrics["active_subs"]} subscribers ({metrics["conversion_rate"]:.1f}% conversion)<br />\n'
        f'• <b>24h Platform Revenue:</b> {metrics["revenue_24h_stars"]} ⭐ / {metrics["revenue_24h_rub"]} ₽ (~${metrics["revenue_24h_usd"]:.2f})<br />\n'
        f'• <b>All-Time Platform Revenue:</b> {metrics["stars_revenue"]} ⭐ / {metrics["rub_revenue"]} ₽ (~${metrics["total_estimated_usd"]:.2f})<br />\n'
        f'• <b>Registered B2B Partners:</b> {metrics["total_partners"]} channels<br />\n'
        f'• <b>Affiliate Commissions:</b> {metrics["affiliate_stars"]} ⭐ / {metrics["affiliate_rub"]} ₽ (Pending Payouts: {metrics["pending_payout_count"]})\n'
        f'</callout>'
    )


def format_notion_blocks_json(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generate Notion REST API block objects for appending or updating via HTTP API.
    """
    text_content = (
        f"Live Platform Metrics & SaaS Telemetry (Auto-Synced)\n"
        f"Last Sync: {metrics['timestamp_utc']} | Sync Engine: services.notion_sync\n"
        f"• Total Registered Users: {metrics['total_users']} traders\n"
        f"• Active VIP Subscriptions: {metrics['active_subs']} subscribers ({metrics['conversion_rate']:.1f}% conversion)\n"
        f"• 24h Platform Revenue: {metrics['revenue_24h_stars']} Stars / {metrics['revenue_24h_rub']} RUB (~${metrics['revenue_24h_usd']:.2f})\n"
        f"• All-Time Revenue: {metrics['stars_revenue']} Stars / {metrics['rub_revenue']} RUB (~${metrics['total_estimated_usd']:.2f})\n"
        f"• B2B Partners: {metrics['total_partners']} channels\n"
        f"• Affiliate Commissions: {metrics['affiliate_stars']} Stars / {metrics['affiliate_rub']} RUB (Pending: {metrics['pending_payout_count']})"
    )

    return [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": text_content}
                    }
                ],
                "icon": {
                    "type": "emoji",
                    "emoji": "⚡"
                },
                "color": "green_background"
            }
        }
    ]


class NotionSyncService:
    """
    High-level integration service managing live metrics synchronization
    between the CryptoRadar Pro SaaS database and Notion Command Center.
    """

    def __init__(
        self,
        page_id: Optional[str] = None,
        notion_token: Optional[str] = None,
        db_path: Optional[str] = None,
        state_file: Optional[Path] = None,
    ):
        self.page_id = (page_id or DEFAULT_PAGE_ID).replace("-", "")
        self.token = notion_token or getattr(config, "NOTION_TOKEN", "") or os.getenv("NOTION_TOKEN", "")
        self.db_path = db_path or db.DB_PATH
        self.state_file = state_file or STATE_FILE_PATH
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    async def get_metrics(self) -> Dict[str, Any]:
        """Fetch latest database metrics."""
        return await fetch_platform_metrics(self.db_path)

    def persist_state(self, metrics: Dict[str, Any], sync_status: str = "success") -> None:
        """Cache latest telemetry to static json file for instant local inspection."""
        payload = {
            "last_synced_at": metrics["timestamp_utc"],
            "page_id": self.page_id,
            "status": sync_status,
            "metrics": metrics,
            "command_center_url": f"https://app.notion.com/p/{self.page_id}",
        }
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.debug(f"Metrics state cached at {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to persist state file {self.state_file}: {e}")

    async def sync_via_api(self, metrics: Dict[str, Any]) -> bool:
        """
        Sync metrics to Notion via official REST API if NOTION_TOKEN is provided.
        """
        if not self.token:
            logger.info("NOTION_TOKEN not configured. Skipping direct HTTP REST sync.")
            return False

        import urllib.request
        import urllib.error

        url = f"https://api.notion.com/v1/blocks/{self.page_id}/children"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        body = json.dumps({"children": format_notion_blocks_json(metrics)}).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="PATCH")
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10))
            if response.status in (200, 201):
                logger.info(f"Successfully synced metrics to Notion page {self.page_id} via REST API.")
                return True
        except Exception as e:
            logger.warning(f"Notion REST API call failed: {e}")
        return False

    def generate_mcp_update_payload(
        self,
        metrics: Dict[str, Any],
        old_callout_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate payload for Notion MCP tool 'notion-update-page'.
        Used when driving updates through Antigravity / Notion MCP server.
        """
        new_callout = format_notion_callout_markdown(metrics)
        return {
            "page_id": self.page_id,
            "command": "update_content",
            "content_updates": [
                {
                    "old_str": old_callout_str or '<callout icon="⚡" color="green_bg">',
                    "new_str": new_callout,
                }
            ],
            "allow_async": False,
        }

    async def sync(self) -> Dict[str, Any]:
        """
        Execute full synchronization cycle:
        1. Query metrics from SQLite database.
        2. Format markdown & REST payloads.
        3. Attempt API sync if token available.
        4. Persist local state snapshot.
        5. Return comprehensive result summary.
        """
        logger.info(f"Starting SaaS metrics sync for Notion Page: {self.page_id}")
        metrics = await self.get_metrics()
        markdown_block = format_notion_callout_markdown(metrics)

        api_synced = False
        if self.token:
            api_synced = await self.sync_via_api(metrics)

        # Persist local snapshot cache
        self.persist_state(metrics, sync_status="synced_api" if api_synced else "synced_local")

        logger.info(
            f"Metrics summary: {metrics['total_users']} users, "
            f"{metrics['active_subs']} VIP subs ({metrics['conversion_rate']}%), "
            f"Revenue: {metrics['stars_revenue']} ⭐ / {metrics['rub_revenue']} ₽ "
            f"(24h: {metrics['revenue_24h_stars']} ⭐ / {metrics['revenue_24h_rub']} ₽), "
            f"Partners: {metrics['total_partners']} channels."
        )

        return {
            "success": True,
            "page_id": self.page_id,
            "metrics": metrics,
            "markdown_block": markdown_block,
            "api_synced": api_synced,
            "state_file": str(self.state_file),
            "command_center_url": f"https://app.notion.com/p/{self.page_id}",
        }

    async def run_periodic_sync(self, interval_seconds: int = 3600) -> None:
        """
        Run continuous periodic background sync.
        Can be spawned as an asyncio task inside the bot or web server.
        """
        logger.info(f"Starting periodic Notion sync daemon (Interval: {interval_seconds}s)")
        while True:
            try:
                await self.sync()
            except Exception as e:
                logger.error(f"Periodic sync encountered an error: {e}", exc_info=True)
            await asyncio.sleep(interval_seconds)


# Global singleton instance
notion_sync_service = NotionSyncService()


def print_cli_summary(result: Dict[str, Any]) -> None:
    """Pretty-print synchronization results to terminal."""
    m = result["metrics"]
    sep = "=" * 70
    print("\n" + sep)
    print("🚀  CRYPTORADAR PRO SAAS — NOTION COMMAND CENTER LIVE SYNC")
    print(sep)
    print(f"📄 Target Notion Page ID: {result['page_id']}")
    print(f"🔗 Command Center URL   : {result['command_center_url']}")
    print(f"⏱️  Timestamp (UTC)     : {m['timestamp_utc']}")
    print(f"💾 Local State Cache    : {result['state_file']}")
    print(f"🌐 Notion REST Sync     : {'✅ Sent via API' if result['api_synced'] else 'ℹ️  Ready (Persisted & MCP Formatted)'}")
    print("-" * 70)
    print("📊 REAL-TIME SAAS TELEMETRY:")
    print(f"  • Registered Users      : {m['total_users']:>6} traders")
    print(f"  • Active VIP Subscribers: {m['active_subs']:>6} subscribers ({m['conversion_rate']:.1f}% conversion)")
    print(f"  • 24h Platform Cashflow : {m['revenue_24h_stars']:>6} ⭐ / {m['revenue_24h_rub']:>6} ₽ (~${m['revenue_24h_usd']:.2f})")
    print(f"  • All-Time Gross Volume : {m['stars_revenue']:>6} ⭐ / {m['rub_revenue']:>6} ₽ (~${m['total_estimated_usd']:.2f})")
    print(f"  • B2B Distribution Net  : {m['total_partners']:>6} channels")
    print(f"  • Affiliate Commissions : {m['affiliate_stars']:>6} ⭐ / {m['affiliate_rub']:>6} ₽ (Pending: {m['pending_payout_count']})")
    print(sep)
    print("✅ SYNC COMPLETED SUCCESSFULLY (Exit Code 0)\n")


async def async_main(args: argparse.Namespace) -> int:
    """Async main routine."""
    service = NotionSyncService(
        page_id=args.page_id,
        notion_token=args.token,
        db_path=args.db,
    )

    if args.loop:
        await service.run_periodic_sync(args.interval)
        return 0

    result = await service.sync()
    if not args.quiet:
        print_cli_summary(result)
    return 0


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Sync live SaaS platform metrics to Notion Command Center.")
    parser.add_argument("--page-id", default=DEFAULT_PAGE_ID, help="Target Notion page ID")
    parser.add_argument("--token", default=None, help="Notion Integration Token")
    parser.add_argument("--db", default=None, help="Path to SQLite database")
    parser.add_argument("--loop", action="store_true", help="Run continuously as background daemon")
    parser.add_argument("--interval", type=int, default=3600, help="Loop interval in seconds (default 3600)")
    parser.add_argument("--quiet", action="store_true", help="Suppress terminal output")
    args = parser.parse_args()

    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
