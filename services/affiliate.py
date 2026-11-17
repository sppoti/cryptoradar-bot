import datetime
from typing import Optional, Dict, Any, Tuple, List
import config
import database as db

DEFAULT_REV_SHARE_RATE = 0.30  # 30% пожизненная ревшара для B2B-партнеров

MIN_PAYOUT_STARS = 50
MIN_PAYOUT_RUB = 100

def calculate_commission(amount: int, rate: float = DEFAULT_REV_SHARE_RATE) -> int:
    """Расчет партнерской комиссии (минимум 1 единица при ненулевой сумме)."""
    if amount <= 0 or rate <= 0:
        return 0
    return max(1, int(round(amount * rate)))

async def process_payment_commission(
    payment_id: int,
    buyer_user_id: int,
    amount: int,
    currency: str,
    tariff_key: str
) -> Optional[Dict[str, Any]]:
    """
    Автоматический расчет и начисление 30% rev-share рефереру при успешной оплате VIP.
    Срабатывает как для Telegram Stars (XTR), так и для рублей (RUB/СБП).
    """
    buyer = await db.get_user(buyer_user_id)
    if not buyer or not buyer.get("referrer_id"):
        return None
        
    partner_id = buyer["referrer_id"]
    if partner_id == buyer_user_id:
        return None
        
    # Убеждаемся, что реферер зарегистрирован в партнерской таблице
    partner = await db.get_partner(partner_id)
    if not partner:
        partner = await db.register_or_get_partner(
            user_id=partner_id,
            partner_code=f"partner_{partner_id}",
            commission_rate=DEFAULT_REV_SHARE_RATE
        )
        
    rate = partner.get("commission_rate") or DEFAULT_REV_SHARE_RATE
    commission = calculate_commission(amount, rate)
    curr = currency.upper()
    
    earning_id = await db.record_affiliate_earning(
        partner_id=partner_id,
        referral_user_id=buyer_user_id,
        payment_id=payment_id,
        tariff_key=tariff_key,
        amount_paid=amount,
        commission_amount=commission,
        currency=curr
    )
    
    return {
        "earning_id": earning_id,
        "partner_id": partner_id,
        "buyer_user_id": buyer_user_id,
        "payment_id": payment_id,
        "tariff_key": tariff_key,
        "amount_paid": amount,
        "commission": commission,
        "currency": curr,
        "rate": rate,
        "rate_percent": int(rate * 100)
    }

async def get_partner_dashboard(user_id: int, bot_username: str) -> Dict[str, Any]:
    """Получение всех метрик для дашборда партнера."""
    stats = await db.get_partner_dashboard_stats(user_id)
    
    clean_bot = bot_username.replace("@", "")
    standard_link = f"https://t.me/{clean_bot}?start=ref_{user_id}"
    
    partner_code = stats.get("partner_code") or f"partner_{user_id}"
    custom_link = f"https://t.me/{clean_bot}?start=ref_{partner_code}"
    
    stats["standard_link"] = standard_link
    stats["custom_link"] = custom_link
    stats["bot_username"] = clean_bot
    stats["rate_percent"] = int(stats.get("commission_rate", DEFAULT_REV_SHARE_RATE) * 100)
    
    return stats

def format_dashboard_text(stats: Dict[str, Any]) -> str:
    """Форматирование карточки дашборда B2B-партнера."""
    code = stats.get("partner_code") or "не установлен"
    custom_link = stats.get("custom_link")
    standard_link = stats.get("standard_link")
    
    rate_pct = stats.get("rate_percent", 30)
    total_traders = stats.get("total_traders", 0)
    active_vips = stats.get("active_vips", 0)
    
    balance_stars = stats.get("balance_stars", 0)
    balance_rub = stats.get("balance_rub", 0)
    earned_stars = stats.get("total_earned_stars", 0)
    earned_rub = stats.get("total_earned_rub", 0)
    payout_details = stats.get("payout_details") or "<i>не указаны (нажмите «Вывести»)</i>"
    
    lines = [
        f"🤝 <b>B2B Партнерский кабинет ({rate_pct}% Rev-Share)</b>",
        "────────────────────",
        f"Монетизируйте вашу аудиторию и Telegram-каналы с пожизненной комиссией <b>{rate_pct}%</b> со всех покупок VIP-подписки (Telegram Stars и СБП).",
        "",
        "📊 <b>Ваша статистика трафика:</b>",
        f"• Привлечено трейдеров: <b>{total_traders}</b> чел.",
        f"• Активных VIP-подписчиков: <b>{active_vips}</b> чел.",
        "",
        "💰 <b>Доходы и баланс:</b>",
        f"• Всего заработано: <b>{earned_stars} ⭐</b> / <b>{earned_rub} ₽</b>",
        f"• Доступно к выводу: <b>{balance_stars} ⭐</b> / <b>{balance_rub} ₽</b>",
        f"• Реквизиты выплат: {payout_details}",
        "",
        "🔗 <b>Ваши персональные реферальные ссылки:</b>",
        f"• <b>Кастомная ссылка:</b>\n<code>{custom_link}</code>",
        f"• <b>Прямой ID-линк:</b>\n<code>{standard_link}</code>",
        f"• <b>Ваш код (slug):</b> <code>{code}</code>",
        "",
        "💡 <i>Используйте готовые промо-посты, TikTok/Reels сценарии и фирменные тизеры ниже, чтобы начать привлекать трейдеров прямо сейчас!</i>"
    ]
    
    recent = stats.get("recent_earnings", [])
    if recent:
        lines.append("")
        lines.append("🕒 <b>Последние начисления:</b>")
        for e in recent[:3]:
            dt = e.get("created_at", "")[:16].replace("T", " ")
            u = "⭐" if e["currency"] == "XTR" else "₽"
            lines.append(f"• +<b>{e['commission_amount']} {u}</b> ({e['tariff_key']}) — <i>{dt}</i>")
            
    return "\n".join(lines)

async def set_custom_slug(user_id: int, new_slug: str) -> Tuple[bool, str]:
    """Установка индивидуального слага партнера."""
    return await db.set_partner_slug(user_id, new_slug)

async def request_payout(
    user_id: int,
    amount: int,
    currency: str,
    details: str
) -> Tuple[bool, str, Optional[int]]:
    """Создание заявки на выплату партнерских средств."""
    curr = currency.upper()
    if curr not in ("XTR", "RUB"):
        return False, "Недопустимая валюта выплаты.", None
        
    min_amount = MIN_PAYOUT_STARS if curr == "XTR" else MIN_PAYOUT_RUB
    unit = "⭐" if curr == "XTR" else "₽"
    
    if amount < min_amount:
        return False, f"Минимальная сумма для вывода: {min_amount} {unit}", None
        
    if not details or len(details.strip()) < 5:
        return False, "Пожалуйста, укажите корректные реквизиты для перевода (номер карты, телефон СБП или адрес кошелька).", None
        
    # Сохраняем последние реквизиты в профиле партнера
    await db.update_partner_payout_details(user_id, details)
    
    return await db.create_payout_request(user_id, amount, curr, details)

async def approve_payout(payout_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Подтверждение выплаты администратором."""
    payout = await db.get_payout_request(payout_id)
    if not payout:
        return False, "Заявка не найдена.", None
        
    if payout["status"] != "pending":
        return False, f"Заявка уже обработана (статус: {payout['status']}).", None
        
    success = await db.update_payout_status(payout_id, "approved")
    if success:
        return True, "Выплата успешно одобрена и отмечена как выполненная.", payout
    return False, "Не удалось обновить статус заявки.", None

async def reject_payout(payout_id: int, reason: str = "") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Отклонение выплаты с автоматическим возвратом средств на баланс партнера."""
    payout = await db.get_payout_request(payout_id)
    if not payout:
        return False, "Заявка не найдена.", None
        
    if payout["status"] != "pending":
        return False, f"Заявка уже обработана (статус: {payout['status']}).", None
        
    success = await db.update_payout_status(payout_id, "rejected")
    if success:
        return True, "Заявка отклонена, средства возвращены на баланс партнера.", payout
    return False, "Не удалось обновить статус заявки.", None

def format_commission_notification(
    commission: int,
    currency: str,
    tariff_title: str,
    rate_percent: int = 30
) -> str:
    """Уведомление партнеру о новом начислении комиссии."""
    unit = "⭐" if currency.upper() == "XTR" else "₽"
    return (
        f"🎉 <b>Партнерское вознаграждение начислено!</b>\n\n"
        f"Ваш реферал только что оплатил тариф <b>«{tariff_title}»</b>.\n"
        f"Ваша ставка rev-share: <b>{rate_percent}%</b>\n"
        f"Вам начислено: <b>+{commission} {unit}</b> на баланс!\n\n"
        f"Проверить баланс и запросить вывод можно в разделе «🤝 Партнерка» (/partner)."
    )

def format_payout_admin_alert(payout: Dict[str, Any], partner: Dict[str, Any]) -> str:
    """Уведомление администратору о новой заявке на вывод."""
    unit = "⭐" if payout["currency"] == "XTR" else "₽"
    return (
        f"💸 <b>Новая заявка на партнерскую выплату #{payout['id']}!</b>\n\n"
        f"Партнер: ID <code>{payout['partner_id']}</code> (Код: <code>{partner.get('partner_code', 'N/A')}</code>)\n"
        f"Сумма: <b>{payout['amount']} {unit}</b>\n"
        f"Реквизиты: <code>{payout['details']}</code>\n\n"
        f"Проверьте данные и подтвердите отправку средств кнопкой ниже."
    )
