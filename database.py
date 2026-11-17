import aiosqlite
import datetime
from typing import Optional, Dict, Any, List, Tuple

DB_PATH = "bot_database.db"

async def init_db():
    """Инициализация базы данных и создание таблиц."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referrer_id INTEGER DEFAULT NULL,
                sub_until TIMESTAMP DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                tariff_key TEXT,
                amount INTEGER,
                currency TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posted_news (
                link TEXT PRIMARY KEY,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posted_alerts (
                symbol TEXT,
                alert_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Таблицы B2B партнерской программы и ревшары
        await db.execute("""
            CREATE TABLE IF NOT EXISTS partners (
                user_id INTEGER PRIMARY KEY,
                partner_code TEXT UNIQUE,
                channel_name TEXT DEFAULT '',
                channel_link TEXT DEFAULT '',
                commission_rate REAL DEFAULT 0.30,
                balance_stars INTEGER DEFAULT 0,
                balance_rub INTEGER DEFAULT 0,
                total_earned_stars INTEGER DEFAULT 0,
                total_earned_rub INTEGER DEFAULT 0,
                payout_details TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS affiliate_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER,
                referral_user_id INTEGER,
                payment_id INTEGER,
                tariff_key TEXT,
                amount_paid INTEGER,
                commission_amount INTEGER,
                currency TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payout_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER,
                amount INTEGER,
                currency TEXT,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP DEFAULT NULL
            )
        """)
        # Таблица участников закрытого VIP-канала
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vip_channel_members (
                user_id INTEGER PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Автоматическая инициализация вечной VIP-подписки для администратора
        import config
        if config.ADMIN_ID:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name, sub_until)
                VALUES (?, 'admin', 'Administrator', '2099-12-31T23:59:59')
                ON CONFLICT(user_id) DO UPDATE SET sub_until = '2099-12-31T23:59:59'
            """, (config.ADMIN_ID,))

        await db.commit()

async def get_or_create_user(user_id: int, username: str, first_name: str, referrer_id: Optional[int] = None) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        
        if not user:
            if referrer_id == user_id:
                referrer_id = None
                
            await db.execute(
                "INSERT INTO users (user_id, username, first_name, referrer_id) VALUES (?, ?, ?, ?)",
                (user_id, username, first_name, referrer_id)
            )
            await db.commit()
            
            if referrer_id:
                await add_subscription_days(referrer_id, 3)
                
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = await cursor.fetchone()
            
        return dict(user)

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        return dict(user) if user else None

async def add_subscription_days(user_id: int, days: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT sub_until FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        
        now = datetime.datetime.now()
        if not row:
            new_date = now + datetime.timedelta(days=days)
            await db.execute(
                "INSERT INTO users (user_id, username, first_name, sub_until) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET sub_until = excluded.sub_until",
                (user_id, "", "Трейдер", new_date.isoformat())
            )
            await db.commit()
            return

        current_sub = None
        if row and row["sub_until"]:
            try:
                current_sub = datetime.datetime.fromisoformat(row["sub_until"])
            except Exception:
                current_sub = None
                
        if current_sub and current_sub > now:
            new_date = current_sub + datetime.timedelta(days=days)
        else:
            new_date = now + datetime.timedelta(days=days)
            
        await db.execute(
            "UPDATE users SET sub_until = ? WHERE user_id = ?",
            (new_date.isoformat(), user_id)
        )
        await db.commit()

async def is_sub_active(user_id: int) -> bool:
    import config
    try:
        if config.ADMIN_ID and int(user_id) == int(config.ADMIN_ID):
            return True
    except (ValueError, TypeError):
        pass
    user = await get_user(user_id)
    if not user or not user["sub_until"]:
        return False
    try:
        sub_date = datetime.datetime.fromisoformat(user["sub_until"])
        return sub_date > datetime.datetime.now()
    except Exception:
        return False

async def get_referral_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_top_referrers(limit: int = 10) -> List[Dict[str, Any]]:
    """Получить топ пользователей по числу приглашенных."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT u.user_id, COALESCE(NULLIF(u.username, ''), u.first_name, 'Участник') as display_name,
                   COUNT(r.user_id) as ref_count
            FROM users u
            JOIN users r ON r.referrer_id = u.user_id
            GROUP BY u.user_id
            ORDER BY ref_count DESC
            LIMIT ?
        """
        cursor = await db.execute(query, (limit,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_user_rank(user_id: int) -> Tuple[int, int]:
    """Возвращает (место в рейтинге, количество рефералов)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        user_refs = (await cursor.fetchone())[0]
        
        if user_refs == 0:
            return (0, 0)
            
        query = """
            SELECT COUNT(*) FROM (
                SELECT referrer_id, COUNT(*) as cnt
                FROM users
                WHERE referrer_id IS NOT NULL
                GROUP BY referrer_id
                HAVING cnt > ?
            )
        """
        cursor = await db.execute(query, (user_refs,))
        higher_count = (await cursor.fetchone())[0]
        return (higher_count + 1, user_refs)

async def record_payment(user_id: int, tariff_key: str, amount: int, currency: str, status: str = "approved") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO payments (user_id, tariff_key, amount, currency, status) VALUES (?, ?, ?, ?, ?)",
            (user_id, tariff_key, amount, currency, status)
        )
        await db.commit()
        return cursor.lastrowid

async def get_payment(payment_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def update_payment_status(payment_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE payments SET status = ? WHERE id = ?", (status, payment_id))
        await db.commit()

async def get_all_users() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

async def get_stats() -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        c1 = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await c1.fetchone())[0]
        
        now = datetime.datetime.now().isoformat()
        c2 = await db.execute("SELECT COUNT(*) FROM users WHERE sub_until > ?", (now,))
        active_subs = (await c2.fetchone())[0]
        
        c3 = await db.execute("SELECT SUM(amount) FROM payments WHERE status = 'approved' AND currency = 'XTR'")
        stars_revenue = (await c3.fetchone())[0] or 0
        
        c4 = await db.execute("SELECT SUM(amount) FROM payments WHERE status = 'approved' AND currency = 'RUB'")
        rub_revenue = (await c4.fetchone())[0] or 0
        
        return {
            "total_users": total_users,
            "active_subs": active_subs,
            "stars_revenue": stars_revenue,
            "rub_revenue": rub_revenue
        }

async def is_news_posted(link: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM posted_news WHERE link = ?", (link,))
        row = await cursor.fetchone()
        return row is not None

async def mark_news_as_posted(link: str, title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO posted_news (link, title) VALUES (?, ?)",
            (link, title)
        )
        await db.commit()

async def can_post_alert(symbol: str, alert_type: str, cooldown_hours: int = 2) -> bool:
    """Проверка, не публиковался ли алерт по этой монете недавно."""
    async with aiosqlite.connect(DB_PATH) as db:
        offset_modifier = f"-{cooldown_hours} hours"
        cursor = await db.execute(
            "SELECT 1 FROM posted_alerts WHERE symbol = ? AND alert_type = ? AND created_at > datetime('now', ?)",
            (symbol, alert_type, offset_modifier)
        )
        row = await cursor.fetchone()
        return row is None

async def record_alert(symbol: str, alert_type: str):
    """Фиксация отправленного алерта."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO posted_alerts (symbol, alert_type) VALUES (?, ?)",
            (symbol, alert_type)
        )
        await db.commit()

# =====================================================================
# B2B ПАРТНЕРСКАЯ ПРОГРАММА И РЕФЕРАЛЬНЫЙ ДВИЖОК (REV-SHARE)
# =====================================================================

async def get_partner(user_id: int) -> Optional[Dict[str, Any]]:
    """Получить данные партнера по user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM partners WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_partner_by_code(code: str) -> Optional[Dict[str, Any]]:
    """Найти партнера по кастомному коду/slug."""
    if not code:
        return None
    clean_code = code.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM partners WHERE LOWER(partner_code) = ? AND is_active = 1",
            (clean_code,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def resolve_referrer_code(ref_code: str) -> Optional[int]:
    """
    Разрешить реферальный код в user_id реферера.
    Поддерживает форматы:
    - ref_12345678 (числовой ID)
    - 12345678 (числовой ID)
    - ref_cryptowhale (кастомный слаг партнера)
    - cryptowhale (кастомный слаг партнера)
    """
    if not ref_code:
        return None
        
    code_str = str(ref_code).strip()
    lower_code = code_str.lower()
    
    if lower_code.startswith("ref_"):
        sub = lower_code[4:].strip()
        if sub.isdigit():
            return int(sub)
        p = await get_partner_by_code(sub)
        if p:
            return p["user_id"]
        p_full = await get_partner_by_code(lower_code)
        if p_full:
            return p_full["user_id"]
            
    if code_str.isdigit():
        return int(code_str)
        
    p = await get_partner_by_code(lower_code)
    if p:
        return p["user_id"]
        
    return None

async def register_or_get_partner(
    user_id: int,
    partner_code: Optional[str] = None,
    channel_name: str = "",
    channel_link: str = "",
    commission_rate: float = 0.30
) -> Dict[str, Any]:
    """Зарегистрировать пользователя как B2B-партнера или вернуть существующего."""
    existing = await get_partner(user_id)
    if existing:
        return existing
        
    code = partner_code.strip() if partner_code else f"partner_{user_id}"
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем уникальность кода, если занят — используем id
        cursor = await db.execute("SELECT user_id FROM partners WHERE LOWER(partner_code) = LOWER(?)", (code,))
        if await cursor.fetchone():
            code = f"partner_{user_id}"
            
        await db.execute("""
            INSERT INTO partners (user_id, partner_code, channel_name, channel_link, commission_rate)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, code, channel_name, channel_link, commission_rate))
        await db.commit()
        
    return await get_partner(user_id)

async def set_partner_slug(user_id: int, new_slug: str) -> Tuple[bool, str]:
    """Установить индивидуальный реферальный slug партнера."""
    clean_slug = new_slug.strip().lower()
    if clean_slug.startswith("ref_"):
        clean_slug = clean_slug[4:].strip()
        
    if len(clean_slug) < 3 or len(clean_slug) > 32:
        return False, "Код должен быть от 3 до 32 символов."
        
    if not clean_slug.replace("_", "").isalnum():
        return False, "Разрешены только латинские буквы, цифры и знак подчеркивания."
        
    if clean_slug.isdigit():
        return False, "Реферальный код не может состоять только из цифр."
        
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем, не занят ли код другим партнером
        cursor = await db.execute(
            "SELECT user_id FROM partners WHERE LOWER(partner_code) = ? AND user_id != ?",
            (clean_slug, user_id)
        )
        row = await cursor.fetchone()
        if row:
            return False, "Этот реферальный код уже занят другим партнером."
            
        await db.execute(
            "UPDATE partners SET partner_code = ? WHERE user_id = ?",
            (clean_slug, user_id)
        )
        await db.commit()
        
    return True, clean_slug

async def update_partner_payout_details(user_id: int, details: str):
    """Обновить реквизиты выплат партнера."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE partners SET payout_details = ? WHERE user_id = ?",
            (details.strip(), user_id)
        )
        await db.commit()

async def record_affiliate_earning(
    partner_id: int,
    referral_user_id: int,
    payment_id: int,
    tariff_key: str,
    amount_paid: int,
    commission_amount: int,
    currency: str
) -> int:
    """Начислить партнерскую комиссию и обновить баланс."""
    curr = currency.upper()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO affiliate_earnings (
                partner_id, referral_user_id, payment_id, tariff_key,
                amount_paid, commission_amount, currency
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (partner_id, referral_user_id, payment_id, tariff_key, amount_paid, commission_amount, curr))
        earning_id = cursor.lastrowid
        
        if curr == "XTR":
            await db.execute("""
                UPDATE partners 
                SET balance_stars = balance_stars + ?,
                    total_earned_stars = total_earned_stars + ?
                WHERE user_id = ?
            """, (commission_amount, commission_amount, partner_id))
        else:
            await db.execute("""
                UPDATE partners 
                SET balance_rub = balance_rub + ?,
                    total_earned_rub = total_earned_rub + ?
                WHERE user_id = ?
            """, (commission_amount, commission_amount, partner_id))
            
        await db.commit()
        return earning_id

async def create_payout_request(
    partner_id: int,
    amount: int,
    currency: str,
    details: str
) -> Tuple[bool, str, Optional[int]]:
    """Создать заявку на вывод партнерских средств."""
    if amount <= 0:
        return False, "Сумма для вывода должна быть больше 0.", None
        
    curr = currency.upper()
    partner = await get_partner(partner_id)
    if not partner:
        return False, "Партнер не найден в системе.", None
        
    balance_key = "balance_stars" if curr == "XTR" else "balance_rub"
    curr_balance = partner.get(balance_key, 0)
    
    if curr_balance < amount:
        unit = "⭐" if curr == "XTR" else "₽"
        return False, f"Недостаточно средств. Доступно к выводу: {curr_balance} {unit}", None
        
    async with aiosqlite.connect(DB_PATH) as db:
        # Списываем баланс в резерв заявки
        if curr == "XTR":
            await db.execute("UPDATE partners SET balance_stars = balance_stars - ? WHERE user_id = ?", (amount, partner_id))
        else:
            await db.execute("UPDATE partners SET balance_rub = balance_rub - ? WHERE user_id = ?", (amount, partner_id))
            
        cursor = await db.execute("""
            INSERT INTO payout_requests (partner_id, amount, currency, details, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (partner_id, amount, curr, details.strip()))
        payout_id = cursor.lastrowid
        await db.commit()
        
    return True, "Заявка на выплату успешно зарегистрирована!", payout_id

async def get_payout_request(payout_id: int) -> Optional[Dict[str, Any]]:
    """Получить информацию о заявке на выплату."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM payout_requests WHERE id = ?", (payout_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_pending_payout_requests() -> List[Dict[str, Any]]:
    """Получить все ожидающие подтверждения заявки на выплату."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT p.*, u.username, u.first_name, pr.partner_code
            FROM payout_requests p
            LEFT JOIN users u ON u.user_id = p.partner_id
            LEFT JOIN partners pr ON pr.user_id = p.partner_id
            WHERE p.status = 'pending'
            ORDER BY p.id ASC
        """
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_partner_payout_requests(partner_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """История заявок на выплату конкретного партнера."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payout_requests WHERE partner_id = ? ORDER BY id DESC LIMIT ?",
            (partner_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def update_payout_status(payout_id: int, status: str) -> bool:
    """Обновить статус выплаты (approved / rejected). При rejected возвращает средства на баланс."""
    payout = await get_payout_request(payout_id)
    if not payout:
        return False
        
    if payout["status"] != "pending":
        return False
        
    partner_id = payout["partner_id"]
    amount = payout["amount"]
    curr = payout["currency"].upper()
    
    async with aiosqlite.connect(DB_PATH) as db:
        if status == "rejected":
            # Возврат средств обратно на партнерский баланс
            if curr == "XTR":
                await db.execute("UPDATE partners SET balance_stars = balance_stars + ? WHERE user_id = ?", (amount, partner_id))
            else:
                await db.execute("UPDATE partners SET balance_rub = balance_rub + ? WHERE user_id = ?", (amount, partner_id))
                
        now = datetime.datetime.now().isoformat()
        await db.execute(
            "UPDATE payout_requests SET status = ?, processed_at = ? WHERE id = ?",
            (status, now, payout_id)
        )
        await db.commit()
    return True

async def get_partner_dashboard_stats(user_id: int) -> Dict[str, Any]:
    """Собрать агрегированные метрики для дашборда партнера."""
    partner = await get_partner(user_id)
    if not partner:
        partner = await register_or_get_partner(user_id)
        
    async with aiosqlite.connect(DB_PATH) as db:
        # Всего привлеченных трейдеров
        c1 = await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        total_traders = (await c1.fetchone())[0]
        
        # Активных VIP-подписчиков среди рефералов
        now = datetime.datetime.now().isoformat()
        c2 = await db.execute(
            "SELECT COUNT(*) FROM users WHERE referrer_id = ? AND sub_until > ?",
            (user_id, now)
        )
        active_vips = (await c2.fetchone())[0]
        
        # Последние 5 начислений
        db.row_factory = aiosqlite.Row
        c3 = await db.execute(
            "SELECT * FROM affiliate_earnings WHERE partner_id = ? ORDER BY id DESC LIMIT 5",
            (user_id,)
        )
        recent_earnings = [dict(r) for r in await c3.fetchall()]
        
    return {
        "user_id": user_id,
        "partner_code": partner["partner_code"],
        "commission_rate": partner["commission_rate"],
        "channel_name": partner["channel_name"],
        "channel_link": partner["channel_link"],
        "payout_details": partner["payout_details"],
        "total_traders": total_traders,
        "active_vips": active_vips,
        "balance_stars": partner["balance_stars"],
        "balance_rub": partner["balance_rub"],
        "total_earned_stars": partner["total_earned_stars"],
        "total_earned_rub": partner["total_earned_rub"],
        "recent_earnings": recent_earnings
    }

async def get_admin_partners_summary() -> Dict[str, Any]:
    """Сводка по всем партнерам для админ-панели."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Всего партнеров
        c1 = await db.execute("SELECT COUNT(*) FROM partners WHERE is_active = 1")
        total_partners = (await c1.fetchone())[0]
        
        # Всего начислено Stars и RUB
        c2 = await db.execute("SELECT SUM(commission_amount) FROM affiliate_earnings WHERE currency = 'XTR'")
        affiliate_stars = (await c2.fetchone())[0] or 0
        
        c3 = await db.execute("SELECT SUM(commission_amount) FROM affiliate_earnings WHERE currency = 'RUB'")
        affiliate_rub = (await c3.fetchone())[0] or 0
        
        # Заявок на выплату в статусе pending
        c4 = await db.execute("SELECT COUNT(*), SUM(CASE WHEN currency = 'XTR' THEN amount ELSE 0 END), SUM(CASE WHEN currency = 'RUB' THEN amount ELSE 0 END) FROM payout_requests WHERE status = 'pending'")
        p_row = await c4.fetchone()
        pending_count = p_row[0] or 0
        pending_stars = p_row[1] or 0
        pending_rub = p_row[2] or 0
        
        return {
            "total_partners": total_partners,
            "affiliate_stars": affiliate_stars,
            "affiliate_rub": affiliate_rub,
            "pending_count": pending_count,
            "pending_stars": pending_stars,
            "pending_rub": pending_rub
        }

# =====================================================================
# УПРАВЛЕНИЕ УЧАСТНИКАМИ ЗАКРЫТОГО VIP-КАНАЛА
# =====================================================================

async def record_vip_channel_join(user_id: int):
    """Фиксация вступления пользователя в закрытый VIP-канал."""
    now = datetime.datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO vip_channel_members (user_id, joined_at, last_check, is_active)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                joined_at = excluded.joined_at,
                last_check = excluded.last_check,
                is_active = 1
        """, (user_id, now, now))
        await db.commit()

async def get_active_vip_channel_members() -> List[Dict[str, Any]]:
    """Получить список всех активных участников закрытого VIP-канала."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM vip_channel_members WHERE is_active = 1")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def mark_vip_channel_left(user_id: int):
    """Пометить пользователя как покинувшего / исключенного из VIP-канала."""
    now = datetime.datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE vip_channel_members SET is_active = 0, last_check = ? WHERE user_id = ?",
            (now, user_id)
        )
        await db.commit()

async def get_expired_vip_members() -> List[Dict[str, Any]]:
    """Получить участников VIP-канала, у которых истекла подписка (sub_until < now или sub_until IS NULL)."""
    now = datetime.datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT v.user_id, v.joined_at, v.last_check, u.username, u.first_name, u.sub_until
            FROM vip_channel_members v
            LEFT JOIN users u ON u.user_id = v.user_id
            WHERE v.is_active = 1 AND (u.sub_until IS NULL OR u.sub_until < ?)
        """
        cursor = await db.execute(query, (now,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def is_vip_channel_member(user_id: int) -> bool:
    """Проверка, числится ли пользователь активным участником VIP-канала в БД."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM vip_channel_members WHERE user_id = ? AND is_active = 1", (user_id,))
        row = await cursor.fetchone()
        return row is not None

async def get_vip_channel_member(user_id: int) -> Optional[Dict[str, Any]]:
    """Получить данные участника VIP-канала."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM vip_channel_members WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def update_vip_member_check(user_id: int):
    """Обновить время последней проверки участника."""
    now = datetime.datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE vip_channel_members SET last_check = ? WHERE user_id = ?", (now, user_id))
        await db.commit()


