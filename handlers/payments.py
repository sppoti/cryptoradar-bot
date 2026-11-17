from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database as db
import keyboards as kb
from services import affiliate, vip_channel

router = Router()

class ManualPaymentState(StatesGroup):
    waiting_for_receipt = State()

# ----------------- ОПЛАТА ЧЕРЕЗ TELEGRAM STARS -----------------

@router.callback_query(F.data.startswith("tariff_"))
async def cb_tariff_detail(callback: CallbackQuery):
    """Выбор тарифа с автоматической выдачей через Telegram Stars."""
    tariff_key = callback.data.replace("tariff_", "")
    tariff = config.TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
        
    text = (
        f"💎 <b>Выбран тариф: {tariff['title']}</b>\n\n"
        f"⏱ <b>Срок действия:</b> {tariff['days']} дней\n"
        f"📝 <b>Описание:</b> {tariff['description']}\n\n"
        f"💰 <b>Стоимость:</b> <b>{tariff['stars']} ⭐</b>\n\n"
        f"⚡ <b>Автоматическая выдача:</b> подписка активируется мгновенно сразу после оплаты Telegram Stars."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_payment_methods(tariff_key))
    await callback.answer()

@router.callback_query(F.data.startswith("pay_stars_"))
async def cb_pay_stars(callback: CallbackQuery):
    tariff_key = callback.data.replace("pay_stars_", "")
    tariff = config.TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer("Ошибка: тариф не найден.", show_alert=True)
        return
        
    user_id = callback.from_user.id
    
    await callback.bot.send_invoice(
        chat_id=user_id,
        title=f"Оплата: {tariff['title']}",
        description=f"{tariff['description']}\n⚡ Автоматическая выдача: подписка активируется мгновенно сразу после оплаты Telegram Stars.",
        payload=f"stars_{tariff_key}_{user_id}",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=tariff['title'], amount=tariff['stars'])],
        provider_token="" # Для Telegram Stars всегда пустая строка
    )
    await callback.answer()

@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout: PreCheckoutQuery):
    """Подтверждение готовности принять платеж в Stars."""
    await pre_checkout.answer(ok=True)

@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    """Успешная оплата через Telegram Stars."""
    payment = message.successful_payment
    user_id = message.from_user.id
    username = message.from_user.username or "Без юзернейма"
    
    # Разбор payload: stars_sub_1m_123456
    parts = payment.invoice_payload.split("_")
    tariff_key = f"{parts[1]}_{parts[2]}" if len(parts) >= 3 else "sub_1m"
    tariff = config.TARIFFS.get(tariff_key, config.TARIFFS["sub_1m"])
    
    # Начисляем подписку
    await db.add_subscription_days(user_id, tariff["days"])
    rec_payment_id = await db.record_payment(user_id, tariff_key, payment.total_amount, "XTR", "approved")
    
    # Автоматическое начисление 30% rev-share партнеру
    try:
        affiliate_res = await affiliate.process_payment_commission(
            payment_id=rec_payment_id,
            buyer_user_id=user_id,
            amount=payment.total_amount,
            currency="XTR",
            tariff_key=tariff_key
        )
        if affiliate_res:
            partner_alert = affiliate.format_commission_notification(
                commission=affiliate_res["commission"],
                currency="XTR",
                tariff_title=tariff["title"],
                rate_percent=affiliate_res.get("rate_percent", 30)
            )
            await message.bot.send_message(affiliate_res["partner_id"], partner_alert, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка начисления партнерской комиссии Stars: {e}")
    
    # Генерация персональной одноразовой ссылки в VIP-канал (с фоллбэком на VIP_LINK)
    vip_link = await vip_channel.create_vip_invite_link(message.bot, user_id)
    if not vip_link:
        vip_link = config.VIP_LINK
    await db.record_vip_channel_join(user_id)

    # Сообщение покупателю
    text = (
        f"🎉 <b>Оплата успешно получена!</b>\n\n"
        f"Тариф: <b>{tariff['title']}</b>\n"
        f"Добавлено дней доступа: <b>+{tariff['days']} дней</b>\n\n"
        f"⚡ <b>Автоматическая выдача:</b> подписка активирована моментально! Доступ ко всем сигналам, AI-прогнозам и PRO-терминалу открыт.\n\n"
        f"👉 <b>Ваша ссылка для входа в VIP-клуб:</b>\n"
        f"<a href='{vip_link}'>Нажмите сюда, чтобы войти в канал</a>\n\n"
        f"Спасибо за доверие!"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb.get_payment_success_keyboard(vip_link=vip_link))
    
    # Уведомление администратору
    if config.ADMIN_ID:
        try:
            admin_notify = (
                f"💰 <b>Новая оплата Stars!</b>\n\n"
                f"Пользователь: @{username} (ID: <code>{user_id}</code>)\n"
                f"Тариф: {tariff['title']}\n"
                f"Сумма: <b>{payment.total_amount} ⭐</b>"
            )
            await message.bot.send_message(config.ADMIN_ID, admin_notify, parse_mode="HTML")
        except Exception:
            pass

# ----------------- ОПЛАТА ПО РЕКВИЗИТАМ (СБП / КАРТА) -----------------

@router.callback_query(F.data.startswith("pay_manual_"))
async def cb_pay_manual(callback: CallbackQuery, state: FSMContext):
    tariff_key = callback.data.replace("pay_manual_", "")
    tariff = config.TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer("Ошибка: тариф не найден.", show_alert=True)
        return
        
    await state.set_state(ManualPaymentState.waiting_for_receipt)
    await state.update_data(tariff_key=tariff_key)
    
    text = (
        f"💳 <b>Оплата тарифа «{tariff['title']}» по СБП/Карте</b>\n\n"
        f"Сумма к оплате: <b>{tariff['rub_price']} ₽</b>\n\n"
        f"{config.MANUAL_PAYMENT_DETAILS}\n\n"
        f"📌 <b>ИНСТРУКЦИЯ:</b>\n"
        f"1. Переведите точную сумму ({tariff['rub_price']} ₽) по реквизитам выше.\n"
        f"2. <b>Отправьте ответным сообщением сюда чек, фото или скриншот перевода.</b>\n\n"
        f"<i>После отправки чека администратор проверит платеж и бот автоматически выдаст вам ссылку.</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.get_back_to_menu())
    await callback.answer()

@router.message(ManualPaymentState.waiting_for_receipt, Command("cancel"))
async def cmd_cancel_manual_payment(message: Message, state: FSMContext):
    """Отмена отправки чека."""
    await state.clear()
    await message.answer("Оплата отменена.", reply_markup=kb.get_tariffs_keyboard())

@router.message(ManualPaymentState.waiting_for_receipt, ~F.photo, ~F.document, ~F.text.startswith("/"))
async def process_invalid_receipt_text(message: Message):
    """Подсказка при отправке текста, стикера или медиа вместо файла или фото чека."""
    await message.answer(
        "❌ <b>Пожалуйста, отправьте чек об оплате в виде фото (скриншота) или файла-документа.</b>\n\n"
        "Если вы хотите отменить оплату, отправьте команду /cancel",
        parse_mode="HTML"
    )

@router.message(ManualPaymentState.waiting_for_receipt, F.photo | F.document)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    tariff_key = data.get("tariff_key", "sub_1m")
    tariff = config.TARIFFS.get(tariff_key, config.TARIFFS["sub_1m"])
    user_id = message.from_user.id
    username = message.from_user.username or "Без юзернейма"
    
    # Фиксируем ожидающую оплату в БД
    payment_id = await db.record_payment(user_id, tariff_key, tariff["rub_price"], "RUB", "pending")
    await state.clear()
    
    await message.answer(
        "✅ <b>Чек успешно принят!</b>\n\n"
        "Мы передали его администратору на проверку. Как только платеж подтвердится, вы сразу получите уведомление и ссылку в закрытый канал.",
        parse_mode="HTML",
        reply_markup=kb.get_back_to_menu()
    )
    
    # Отправляем чек администратору
    if config.ADMIN_ID:
        try:
            caption = (
                f"🔔 <b>Новая заявка на оплату #{payment_id}!</b>\n\n"
                f"Пользователь: @{username} (ID: <code>{user_id}</code>)\n"
                f"Тариф: <b>{tariff['title']}</b> ({tariff['rub_price']} ₽)\n"
                f"Дней: +{tariff['days']}"
            )
            
            # Пересылаем фото или документ
            if message.photo:
                await message.bot.send_photo(
                    config.ADMIN_ID,
                    photo=message.photo[-1].file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=kb.get_confirm_payment_keyboard(payment_id)
                )
            elif message.document:
                await message.bot.send_document(
                    config.ADMIN_ID,
                    document=message.document.file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=kb.get_confirm_payment_keyboard(payment_id)
                )
        except Exception as e:
            print(f"Ошибка отправки чека админу: {e}")

# ----------------- ПОДТВЕРЖДЕНИЕ ЧЕКОВ АДМИНИСТРАТОРОМ -----------------

@router.callback_query(F.data.startswith("adm_approve_"))
async def cb_admin_approve(callback: CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("У вас нет прав.", show_alert=True)
        return
        
    payment_id = int(callback.data.replace("adm_approve_", ""))
    payment = await db.get_payment(payment_id)
    
    if not payment:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
        
    if payment["status"] != "pending":
        await callback.answer(f"Заявка уже в статусе: {payment['status']}", show_alert=True)
        return
        
    user_id = payment["user_id"]
    tariff = config.TARIFFS.get(payment["tariff_key"], config.TARIFFS["sub_1m"])
    
    await db.update_payment_status(payment_id, "approved")
    await db.add_subscription_days(user_id, tariff["days"])
    
    # Автоматическое начисление 30% rev-share партнеру
    try:
        affiliate_res = await affiliate.process_payment_commission(
            payment_id=payment_id,
            buyer_user_id=user_id,
            amount=payment["amount"],
            currency="RUB",
            tariff_key=payment["tariff_key"]
        )
        if affiliate_res:
            partner_alert = affiliate.format_commission_notification(
                commission=affiliate_res["commission"],
                currency="RUB",
                tariff_title=tariff["title"],
                rate_percent=affiliate_res.get("rate_percent", 30)
            )
            await callback.bot.send_message(affiliate_res["partner_id"], partner_alert, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка начисления партнерской комиссии RUB: {e}")
    
    # Генерация персональной одноразовой ссылки в VIP-канал (с фоллбэком на VIP_LINK)
    vip_link = await vip_channel.create_vip_invite_link(callback.bot, user_id)
    if not vip_link:
        vip_link = config.VIP_LINK
    await db.record_vip_channel_join(user_id)

    # Уведомляем пользователя
    try:
        user_msg = (
            f"🎉 <b>Ваш платеж #{payment_id} подтвержден!</b>\n\n"
            f"Вам начислен тариф: <b>{tariff['title']}</b> (+{tariff['days']} дней).\n\n"
            f"👉 <b>Ваша ссылка в VIP-клуб:</b>\n"
            f"<a href='{vip_link}'>Войти в закрытый канал</a>"
        )
        await callback.bot.send_message(user_id, user_msg, parse_mode="HTML", reply_markup=kb.get_payment_success_keyboard(vip_link=vip_link))
    except Exception:
        pass
        
    await callback.message.edit_caption(
        caption=f"{callback.message.caption or ''}\n\n✅ <b>ОДОБРЕНО администратором</b>",
        parse_mode="HTML"
    )
    await callback.answer("Платеж успешно подтвержден!")

@router.callback_query(F.data.startswith("adm_reject_"))
async def cb_admin_reject(callback: CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("У вас нет прав.", show_alert=True)
        return
        
    payment_id = int(callback.data.replace("adm_reject_", ""))
    payment = await db.get_payment(payment_id)
    
    if not payment:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
        
    user_id = payment["user_id"]
    await db.update_payment_status(payment_id, "rejected")
    
    try:
        await callback.bot.send_message(
            user_id,
            "❌ <b>Ваш платеж был отклонен администратором.</b>\n\n"
            "Если произошла ошибка или вы перевели средства, пожалуйста, свяжитесь со службой поддержки через раздел «💬 Поддержка».",
            parse_mode="HTML"
        )
    except Exception:
        pass
        
    await callback.message.edit_caption(
        caption=f"{callback.message.caption or ''}\n\n❌ <b>ОТКЛОНЕНО администратором</b>",
        parse_mode="HTML"
    )
    await callback.answer("Платеж отклонен.")
