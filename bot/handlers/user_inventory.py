import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database.models import User, ShopItem, StockUnit

router = Router(name="user_inventory_router")
logger = logging.getLogger(__name__)

# --- 🎒 ГЛАВНЫЙ ИНВЕНТАРЬ ПОЛЬЗОВАТЕЛЯ ---

@router.message(F.text == "🎒 Мой Инвентарь / Награды")
@router.callback_query(F.data == "user_inventory_main")
@router.callback_query(F.data.startswith("u_inv_page:"))
async def cmd_user_inventory_main(message_or_query, db_session: AsyncSession, db_user: User):
    """Вывод поштучного инвентаря пользователя из ERP таблицы StockUnit."""
    page = 1
    is_callback = isinstance(message_or_query, CallbackQuery)
    
    if is_callback and message_or_query.data.startswith("u_inv_page:"):
        page = int(message_or_query.data.split(":"))
        
    limit = 5
    offset = (page - 1) * limit
    
    # Считаем только выданные/выигранные единицы товара, принадлежащие юзеру
    count_q = select(func.count(StockUnit.id)).where(
        and_(StockUnit.owner_id == db_user.tg_id, StockUnit.status.in_(["sold", "won"]))
    )
    total = (await db_session.execute(count_q)).scalar() or 0
    
    # Загружаем поштучные предметы с подгрузкой их мета-карточек ShopItem
    units_q = select(StockUnit).where(
        and_(StockUnit.owner_id == db_user.tg_id, StockUnit.status.in_(["sold", "won"]))
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
        
    buttons.append([InlineKeyboardButton(text="↩️ В главное меню ЛК", callback_data="user_lk_main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if is_callback:
        try: await message_or_query.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception: pass
    else:
        await message_or_query.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- 🔎 ДЕТАЛЬНЫЙ ПРОСМОТР ПРЕДМЕТА ИЗ ИНВЕНТАРЯ ---

@router.callback_query(F.data.startswith("u_inv_view:"))
async def process_user_inventory_view_click(
    callback: CallbackQuery, db_session: AsyncSession
):
    """Отображение карточки конкретной единицы товара с промокодом."""
    parts = callback.data.split(":")
    unit_id = int(parts)
    page = int(parts)
    
    # Подгружаем StockUnit вместе со связанным ShopItem
    unit = await db_session.get(StockUnit, unit_id)
    if not unit or unit.status not in ["sold", "won"]:
        await callback.answer("❌ Предмет не найден в инвентаре!", show_alert=True)
        return
        
    item = unit.item
    item_name = item.name if item else f"Предмет #{unit.item_id}"
    
    # Определяем источник получения для No-Code логов
    source_lbl = "🛒 Магазин" if unit.purchase_source == "tg" else "🎁 Розыгрыш/Сундук"
    
    # Проверяем наполнение серийника или статуса доставки
    serial_text = "📦 Физический мерч (данные переданы менеджеру)"
    if unit.serial_or_promo:
        if unit.serial_or_promo.startswith("[ДОСТАВКА]:"):
            # Если это физический мерч, отображаем контакты доставки
            serial_text = f"🚛 **Статус:** Оформлена доставка\n📝 {unit.serial_or_promo}"
        else:
            # Если это цифровой ключ/промокод
            serial_text = f"🔑 **Ваш промокод / лицензионный ключ:**\n<code>{unit.serial_or_promo}</code>"
    else:
        if item and item.is_ticket:
            serial_text = "🎟️ Лотерейный билет зафиксирован в пуле участников."

    text = (
        f"🎒 **Карточка предмета из инвентаря**\n\n"
        f"📦 **Название:** {item_name}\n"
        f"🆔 **Уникальный ID единицы:** `{unit.id}`\n"
        f"📥 **Источник получения:** `{source_lbl}`\n"
        f"📅 **Дата получения:** {unit.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"{serial_text}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад к инвентарю", callback_data=f"u_inv_page:{page}")]
    ])
    
    try:
        await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.answer()

