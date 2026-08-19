import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import joinedload
from database.models import User, ShopItem, StockUnit

router = Router(name="user_inventory_router")
logger = logging.getLogger(__name__)

# --- 🎒 ГЛАВНЫЙ ИНВЕНТАРЬ ПОЛЬЗОВАТЕЛЯ ---

@router.message(F.text == "🎒 Мой Инвентарь / Награды")
@router.callback_query(F.data == "user_inventory_main")
@router.callback_query(F.data.startswith("u_inv_page:"))
async def cmd_user_inventory_main(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    """Вывод поштучного инвентаря пользователя с жадной загрузкой связей товара."""
    page = 1
    if callback.data.startswith("u_inv_page:"):
        page = int(callback.data.split(":")[1])
        
    limit = 4
    offset = (page - 1) * limit
    
    # Считаем общее количество вещей у пользователя
    count_q = select(func.count(StockUnit.id)).where(
        and_(StockUnit.owner_id == db_user.tg_id, StockUnit.status.in_(["sold", "won"]))
    )
    total = (await db_session.execute(count_q)).scalar() or 0
    
    units_q = select(StockUnit).options(
        joinedload(StockUnit.item)
    ).where(
        and_(
            StockUnit.owner_id == db_user.tg_id,
            StockUnit.status.in_(["sold", "won"])
        )
    ).order_by(StockUnit.created_at.desc()).limit(limit).offset(offset)
    
    units = (await db_session.execute(units_q)).scalars().all()

    
    text = (
        "🎒 **Ваш личный инвентарь наград**\n\n"
        "Здесь хранятся все ваши No-Code покупки, лотерейные билеты и "
        "призы, выигранные в сундуках активности чата.\n\n"
        f"Всего предметов в инвентаре: **{total}** шт."
    )
    
    buttons = []
    for unit in units:
        # Тянем имя товара из связанной модели ShopItem
        item_name = unit.item.name if unit.item else f"Предмет #{unit.item_id}"
        type_icon = "🎟️" if unit.item and unit.item.is_ticket else "🎒"
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{type_icon} {item_name} (ID: {unit.id})", 
                callback_data=f"u_inv_view:{unit.id}:{page}"
            )
        ])
        
    # Пагинация стрелок
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"u_inv_page:{page-1}"))
    if page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"u_inv_page:{page+1}"))
  
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([
        InlineKeyboardButton(text="↩️ Вернуться в меню ЛК", callback_data="user_lk_main")
    ])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    has_media = bool(callback.message.photo or callback.message.animation or callback.message.document)
    
    if has_media:
        # Если откатываемся с картинки — удаляем её и шлём список чистым текстом
        try: await callback.message.delete()
        except Exception: pass
        
        await callback.message.answer(
            text=text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        # Если переключаем обычные текстовые страницы — плавно редактируем на месте
        try:
            await callback.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception: pass
        
    await callback.answer()



@router.callback_query(F.data.startswith("inv_view:"))
async def process_user_inventory_view_click(callback: CallbackQuery, db_session: AsyncSession):
    """Безопасный просмотр карточки предмета инвентаря с гарантированным гашением часиков."""
    try:
        unit_id = int(callback.data.split(":")[1])
        
        # 1. Получаем единицу товара со Склада
        unit_q = select(StockUnit).where(StockUnit.id == unit_id)
        unit = (await db_session.execute(unit_q)).scalar_one_or_none()
        
        if not unit:
            await callback.answer("❌ Предмет не найден в вашем инвентаре.", show_alert=True)
            return

        # 2. Получаем карточку самого товара
        item_q = select(ShopItem).where(ShopItem.id == unit.item_id)
        shop_item = (await db_session.execute(item_q)).scalar_one_or_none()

        # 3. Собираем чистый текст описания БЕЗ Markdown-форматирования внутри переменных
        # чтобы Telegram не ругался на спецсимволы в описаниях товаров
        item_name = shop_item.name
        item_desc = shop_item.description or "Нет описания"
        item_source = unit.purchase_source or "Магазин"
        
        text = (
            f"📦 <b>Предмет:</b> {item_name}\n"
            f"📝 <b>Описание:</b> {item_desc}\n"
            f"🔍 <b>Источник получения:</b> {item_source}\n"
            f"🆔 <b>Уникальный ID предмета:</b> <code>{unit.id}</code>\n\n"
        )

        kb_buttons = []

        # 4. Проверяем реквизиты (Безопасно к None и строго в HTML под parse_mode)
        if unit.serial_or_promo and unit.serial_or_promo.startswith("[ЗАЯВКА]:"):
            delivery_info = unit.serial_or_promo.replace("[ЗАЯВКА]:", "").strip()
            text += (
                f"⏳ <b>Статус:</b> Ожидает отправки менеджером\n"
                f"📍 <b>Ваши реквизиты:</b>\n<i>{delivery_info}</i>"
            )

        elif unit.serial_or_promo and unit.serial_or_promo.startswith("[ВЫДАНО]:"):
            archive_info = unit.serial_or_promo.replace("[ВЫДАНО]:", "").strip()
            text += (
                f"✅ <b>Статус:</b> Доставлено / Выдано\n"
                f"ℹ️ <b>Информация от админа:</b>\n<i>{archive_info}</i>"
            )

        elif unit.serial_or_promo:
            text += (
                f"🔑 <b>Ваш промокод / Ключ активации:</b>\n"
                f"<code>{unit.serial_or_promo}</code>"
            )

        else:
            # Сюда залетают все физические выигрыши из сундуков (у которых serial_or_promo == None)
            text += (
                f"🛑 <b>Статус:</b> Реквизиты доставки не заполнены.\n\n"
                f"💡 Для получения этого товара, нажмите кнопку ниже и "
                f"оставьте данные для отправки (СДЭК, криптокошелёк)."
            )
            kb_buttons.append([
                InlineKeyboardButton(
                    text="📍 Ввести реквизиты доставки", 
                    callback_data=f"inv_delivery_start:{unit.id}"
                )
            ])

        # Кнопка возврата в общее меню инвентаря
        kb_buttons.append([
            InlineKeyboardButton(text="⬅️ Назад в инвентарь", callback_data="user_inventory_main")
        ])
        
        current_kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

        # 5. ОТПРАВКА КАРТОЧКИ (Метод бесшовного пересоздания сообщения, как на стр 14)
        # Отправляем новое чистое текстовое сообщение пользователю
        await callback.message.answer(text, reply_markup=current_kb, parse_mode="HTML")
        
        # Удаляем старое сообщение (на котором была картинка/гифка), чтобы чат оставался чистым
        try:
            await callback.message.delete()
        except Exception:
            pass

    except Exception as e:
        # Если произошел непредвиденный сбой, пишем его в логи консоли
        logger.error(f"Ошибка в просмотре инвентаря: {e}", exc_info=True)
        await callback.answer("⚠️ Произошла ошибка при открытии карточки товара.", show_alert=True)
    
    finally:
        # ЭТОТ БЛОК ВЫПОЛНИТСЯ ВСЕГДА: часики на кнопке гарантированно погаснут!
        await callback.answer()


# --- 🚛 FSM-ОФОРМЛЕНИЕ ДОСТАВКИ ИЗ ИНВЕНТАРЯ ---

@router.callback_query(F.data.startswith("u_inv_claim:"))
async def process_user_inventory_claim_start(callback: CallbackQuery, state: FSMContext):
    """Инициализация FSM-сбора реквизитов доставки для выигранного/купленного мерча."""
    parts = callback.data.split(":")
    
    unit_id = int(parts[1])
    
    await state.update_data(claim_unit_id=unit_id)
    
    from bot.states import UserInventoryClaimSetup # Проверь имя своего класса стейтов
    await state.set_state(UserInventoryClaimSetup.waiting_for_address)

    try: await callback.message.delete()
    except Exception: pass
    
    await callback.message.answer(
        "📦 **Оформление получения награды**\n\n"
        "• Если это **вещевой мерч**, пожалуйста, введите адрес доставки СДЭК, "
        "ФИО и ваш контактный номер телефона одной строкой.\n"
        "• Если это **цифровой ваучер/крипта**, введите адрес вашего кошелька.\n\n"
        "📝 Отправьте ваши реквизиты сообщением в чат бота:"
    )
    await callback.answer()

@router.message(F.state == "UserPurchaseSetup:waiting_for_delivery")
async def process_u_inv_setup_delivery_save(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    """Сохранение реквизитов и активация заявки в админ-очереди."""
    delivery_text = message.text.strip()
    data = await state.get_data()
    unit_id = data.get("setup_unit_id")
    page = data.get("setup_page")
    
    unit = await db_session.get(StockUnit, unit_id)
    if not unit or unit.serial_or_promo != "[НЕ ОФОРМЛЕНО]":
        await message.answer("❌ Ошибка! Товар уже оформлен или не найден.")
        await state.clear()
        return
        
    # ПЕРЕВОДИМ В СТАТУС АКТИВНОЙ ЗАЯВКИ ДЛЯ ОЧЕРЕДИ АДМИНА
    unit.serial_or_promo = f"[ЗАЯВКА]: {delivery_text}"
    await db_session.commit()
    await state.clear()
    
    await message.answer(
        "🎉 **Реквизиты успешно сохранены!**\n\n"
        "Заявка передана администрации и встала в очередь на отправку. "
        "Вы получите уведомление в этот чат, как только статус изменится."
    )
    
    # Анонсируем менеджерам о новой заполненной заявке
    for manager_id in settings.managers_list:
        try:
            item_name = unit.item.name if unit.item else "Мерч"
            await message.bot.send_message(
                chat_id=manager_id,
                text=f"📥 **Пользователь оформил заявку из Инвентаря!**\n\n"
                     f"📦 Товар: *{item_name}* (ID единицы: {unit.id})\n"
                     f"📋 **Реквизиты:** `{delivery_text}`",
                parse_mode="Markdown"
            )
        except Exception: pass
