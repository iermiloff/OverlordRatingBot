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


from aiogram.types import InputMediaPhoto, InputMediaAnimation
from bot.states import UserInventoryClaimSetup # Гарантируем правильный импорт стейтов

@router.callback_query(F.data.startswith("u_inv_view:"))
async def process_user_inventory_view_click(callback: CallbackQuery, db_session: AsyncSession):
    """Просмотр конкретного предмета с выводом его картинки и исправленной кнопкой."""
    parts = callback.data.split(":")
    unit_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1
    
    unit_q = select(StockUnit).where(StockUnit.id == unit_id)
    unit = (await db_session.execute(unit_q)).scalar_one_or_none()
    
    if not unit:
        await callback.answer("❌ Предмет не найден.", show_alert=True)
        return

    item_q = select(ShopItem).where(ShopItem.id == unit.item_id)
    shop_item = (await db_session.execute(item_q)).scalar_one_or_none()

    text = (
        f"📦 **Предмет:** {shop_item.name}\n"
        f"📝 **Описание:** {shop_item.description or 'Нет описания'}\n"
        f"🔍 **Источник получения:** {unit.purchase_source or 'Магазин'}\n"
        f"🆔 **Уникальный ID предмета:** `{unit.id}`\n\n"
    )

    kb_buttons = []
    promo_value = getattr(unit, 'serial_or_promo', '') or ''

    # Логика статусов
    if promo_value.startswith("[ЗАЯВКА]:"):
        delivery_info = promo_value.replace("[ЗАЯВКА]:", "").strip()
        text += f"⏳ **Статус:** Ожидает обработки менеджером\n📍 **Ваши реквизиты:**\n_{delivery_info}_"
    elif promo_value.startswith("[ВЫДАНО]:"):
        archive_info = promo_value.replace("[ВЫДАНО]:", "").strip()
        text += f"✅ **Статус:** Доставлено / Выдано\nℹ️ **Информация от админа:**\n_{archive_info}_"
    elif promo_value != '':
        text += f"🔑 **Ваш промокод / Ключ активации:**\n`{unit.serial_or_promo}`"
    else:
        text += (
            f"🛑 **Статус:** Реквизиты для получения не заполнены.\n\n"
            f"💡 Для получения этой награды, нажмите кнопку ниже и "
            f"оставьте данные (ФИО/Адрес для мерча или крипто-кошелек)."
        )
        # ИСПРАВЛЕНО: Префикс u_inv_claim для точного перехвата хэндлером
        kb_buttons.append([
            InlineKeyboardButton(text="📍 Ввести реквизиты для получения", callback_data=f"u_inv_claim:{unit.id}")
        ])

    # Кнопка возврата с сохранением страницы пагинации
    kb_buttons.append([
        InlineKeyboardButton(text="⬅️ Назад в инвентарь", callback_data=f"u_inv_page:{page}")
    ])
    
    current_kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    # ВЫВОД КАРТИНКИ: Проверяем, загружена ли картинка/гифка в ShopItem (поле image или photo)
    # В зависимости от структуры твоей модели ShopItem, замени shop_item.image на нужное поле
    item_image = getattr(shop_item, 'image', None) or getattr(shop_item, 'photo', None)

    if item_image:
        # Если у товара есть картинка — удаляем текстовое меню списка и шлем красивую медиа-карточку
        try: await callback.message.delete()
        except Exception: pass
        
        # Проверяем по расширению, картинка это или гифка
        if str(item_image).endswith('.gif'):
            await callback.message.answer_animation(animation=item_image, caption=text, reply_markup=current_kb, parse_mode="Markdown")
        else:
            await callback.message.answer_photo(photo=item_image, caption=text, reply_markup=current_kb, parse_mode="Markdown")
    else:
        # Если картинки нет, плавно редактируем текст на месте
        try:
            await callback.message.edit_text(text=text, reply_markup=current_kb, parse_mode="Markdown")
        except Exception:
            await callback.message.answer(text=text, reply_markup=current_kb, parse_mode="Markdown")
            
    await callback.answer()


# --- FSM-ОФОРМЛЕНИЕ ДОСТАВКИ ИЗ ИНВЕНТАРЯ (ИСПРАВЛЕНО) ---
@router.callback_query(F.data.startswith("u_inv_claim:"))
async def process_user_inventory_claim_start(callback: CallbackQuery, state: FSMContext):
    """Инициализация FSM-сбора реквизитов получения."""
    parts = callback.data.split(":")
    unit_id = int(parts[1])
    
    # Сохраняем ID предмета в текущий контекст FSM
    await state.update_data(claim_unit_id=unit_id)
    await state.set_state(UserInventoryClaimSetup.waiting_for_address)
    
    try: await callback.message.delete()
    except Exception: pass
    
    await callback.message.answer(
        " **Оформление получения награды**\n\n"
        f"• Если это **вещевой мерч**, введите адрес доставки СДЭК, ФИО и телефон одной строкой.\n"
        f"• Если это **цифровой ваучер или криптовалюта**, введите адрес вашего кошелька и сеть.\n\n"
        " Отправьте ваши реквизиты ответным сообщением в чат бота:"
    )
    await callback.answer()


# ХЭНДЛЕР ПРИЕМА ТЕКСТА РЕКВИЗИТОВ (ИСПРАВЛЕНО СОСТОЯНИЕ)
@router.message(UserInventoryClaimSetup.waiting_for_address)
async def process_u_inv_setup_delivery_save(message: Message, state: FSMContext, db_session: AsyncSession):
    """Сохранение реквизитов и активация заявки в базе данных."""
    delivery_text = message.text.strip()
    data = await state.get_data()
    unit_id = data.get("claim_unit_id") # Берем правильный ключ из кэша
    
    unit = await db_session.get(StockUnit, unit_id)
    
    # Проверяем, что предмет реален и еще не оформлен (поле пустое или None)
    if not unit or (unit.serial_or_promo and unit.serial_or_promo != ""):
        await message.answer("❌ Ошибка! Товар уже оформлен или не найден в системе.")
        await state.clear()
        return
        
    # Переводим предмет в статус активной заявки для CRM менеджеров
    unit.serial_or_promo = f"[ЗАЯВКА]: {delivery_text}"
    await db_session.commit()
    await state.clear()
    
    await message.answer(
        " **Реквизиты успешно сохранены!**\n\n"
        "Заявка передана администрации. Менеджеры проверят реквизиты и отправят ваш приз. "
        "Вы получите уведомление в этот чат, как только статус изменится!"
    )
    
    # Мгновенное CRM-уведомление администраторам в личку
    for manager_id in settings.managers_list:
        try:
            item_name = unit.item.name if unit.item else "Мерч"
            await message.bot.send_message(
                chat_id=manager_id,
                text=f" **Новая заявка на получение приза из Инвентаря!**\n\n"
                     f"**Пользователь:** {message.from_user.mention_html()}\n"
                     f" **Товар:** *{item_name}* (ID единицы: {unit.id})\n"
                     f" **Реквизиты:** `{delivery_text}`",
                parse_mode="HTML"
            )
        except Exception: 
            pass
