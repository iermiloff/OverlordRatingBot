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



@router.callback_query(F.data.startswith("u_inv_view:"))
async def process_user_inventory_view_click(
    callback: CallbackQuery, db_session: AsyncSession
):
    """Просмотр предмета из инвентаря с жадной загрузкой связей товара."""
    parts = callback.data.split(":")
    unit_id = int(parts[1])
    page = int(parts[2])

    unit_q = select(StockUnit).options(
        joinedload(StockUnit.item)
    ).where(StockUnit.id == unit_id)
    
    unit = (await db_session.execute(unit_q)).scalar_one_or_none()
    
    if not unit or unit.status not in ["sold", "won"]:
        await callback.answer("❌ Предмет не найден!", show_alert=True)
        return
        
    item = unit.item
    item_name = item.name if item else f"Предмет #{unit.item_id}"
    
    buttons = []
    serial_text = ""
    
    if unit.serial_or_promo == "[НЕ ОФОРМЛЕНО]":
        serial_text = (
            "⚠️ **Получение товара не оформлено!**\n\n"
            "Нажмите кнопку ниже, чтобы ввести адрес доставки СДЭК/Почты "
            "или реквизиты кошелька для выплаты."
        )
        buttons.append([
            InlineKeyboardButton(
                text="🚛 Оформить получение", 
                callback_data=f"u_inv_setup_delivery:{unit_id}:{page}"
            )
        ])
    elif unit.serial_or_promo.startswith("[ЗАЯВКА]:"):
        reqs = unit.serial_or_promo.replace("[ЗАЯВКА]:", "").strip()
        serial_text = f"⏳ **Статус:** Ожидает отправки администрацией\n📋 **Ваши реквизиты:** `{reqs}`"
    elif unit.serial_or_promo.startswith("[ВЫДАНО]:"):
        reqs = unit.serial_or_promo.replace("[ВЫДАНО]:", "").strip()
        serial_text = f"✅ **Статус:** Выдано / Отправлено!\n📋 **Данные:** `{reqs}`"
    else:
        serial_text = f"🔑 **Лицензионный промокод/ключ:**\n<code>{unit.serial_or_promo}</code>"

    text = (
        f"🎒 **Карточка предмета из инвентаря**\n\n"
        f"📦 **Название:** {item_name}\n"
        f"🆔 **Уникальный ID единицы:** `{unit.id}`\n\n"
        f"{serial_text}"
    )
    
    buttons.append([InlineKeyboardButton(text="↩️ Назад к инвентарю", callback_data=f"u_inv_page:{page}")])
    reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    # ✅ СТРОГО ИСПРАВЛЕНО: Живой No-Code вывод картинок и гифок товара в инвентаре
    if item and item.image_url:
        # Удаляем старое текстовое меню, чтобы красиво перерисовать карточку с медиа
        try: await callback.message.delete()
        except Exception: pass
        
        # Проверяем расширение файла или маркер анимации для поддержки гифок
        is_gif = item.image_url.endswith(".gif") or "animation" in item.image_url.lower()
        
        if is_gif:
            await callback.message.answer_animation(
                animation=item.image_url,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            await callback.message.answer_photo(
                photo=item.image_url,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
    else:
        # Если у товара нет изображения — плавно обновляем обычным текстом
        try:
            await callback.message.edit_text(
                text=text, 
                reply_markup=reply_markup, 
                parse_mode="HTML"
            )
        except Exception: pass
        
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
