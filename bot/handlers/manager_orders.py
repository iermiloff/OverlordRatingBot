import logging
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from config import settings
from database.models import User, Order, OrderStatus

router = Router(name="manager_orders_router")
logger = logging.getLogger(__name__)

# --- 📥 ГЛАВНЫЙ ПЕРЕХВАТЧИК СТРАНИЦ ЗАКАЗОВ ---

@router.callback_query(F.data.startswith("mg_orders_page:"))
async def process_manager_orders_page_click(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Безопасный перехват клика по кнопке пагинации заявок."""
    if not is_manager: return
    
    # СТРОГО ИСПРАВЛЕНО: Извлекаем номер страницы через индекс [1]
    page = int(callback.data.split(":")[1])
    
    # Вызываем рендеринг страницы без мутации callback.data
    await render_manager_orders_page(
        callback=callback,
        page=page,
        db_session=db_session
    )

# --- 📥 БЕЗОПАСНЫЙ ВЫВОД СТРАНИЦЫ ЗАЯВКOК И ЗАКАЗОВ ---

async def render_manager_orders_page(
    callback: CallbackQuery, 
    page: int, 
    db_session: AsyncSession
):
    """Строгая функция отрисовки заказов с постраничной пагинацией."""
    limit = 5
    offset = (page - 1) * limit
    
    count_q = select(func.count(Order.id))
    total = (await db_session.execute(count_q)).scalar() or 0
    
    orders_q = select(Order).order_by(
        Order.created_at.desc()
    ).limit(limit).offset(offset)
    orders = (await db_session.execute(orders_q)).scalars().all()
    
    text = (
        f"📥 **Управление заявками и заказами мерча**\n\n"
        f"Всего заявок в системе: **{total}** шт.\n"
        f"Текущая страница: `{page}`\n\n"
        f"👇 Нажмите на заказ для изменения его статуса или удаления:"
    )
    
    buttons = []
    for o in orders:
        status_emoji = "⏳" if o.status == "created" else "✅"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status_emoji} Заказ #{o.id} | ID: {o.user_id}", 
                callback_data=f"mg_order_view:{o.id}:{page}"
            )
        ])
        
    nav_row = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"mg_orders_page:{page-1}"
            )
        )
    if page * limit < total:
        nav_row.append(
            InlineKeyboardButton(
                text="Вперед ➡️", callback_data=f"mg_orders_page:{page+1}"
            )
        )
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([
        InlineKeyboardButton(
            text="↩️ Вернуться в корень админки", 
            callback_data="main_menu_manager"
        )
    ])
    
    try:
        await callback.message.edit_text(
            text=text, 
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), 
            parse_mode="Markdown"
        )
    except Exception:
        await callback.answer()

# --- 🔎 ДЕТАЛЬНЫЙ ПРОСМОТР И УПРАВЛЕНИЕ ЗАКАЗОМ ---

@router.callback_query(F.data.startswith("mg_order_view:"))
async def process_manager_order_view_click(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    
    parts = callback.data.split(":")
    order_id = int(parts[1])
    page = int(parts[2])
    
    order = await db_session.get(Order, order_id)
    if not order:
        await callback.answer("❌ Заказ не найден!", show_alert=True)
        return
        
    status_label = "⏳ В обработке" if order.status == "created" else "✅ Выдан"
    text = (
        f"📦 **Просмотр заявки #{order.id}**\n\n"
        f"👤 **ID Пользователя:** <code>{order.user_id}</code>\n"
        f"🎒 **Товар:** *{order.item_name}*\n"
        f"📊 **Текущий статус:** `{status_label}`\n"
        f"📅 **Дата создания:** {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📋 **Данные доставки:**\n_{order.delivery_data}_"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Отметить: Выдан", 
                callback_data=f"mg_order_approve:{order_id}:{page}"
            ),
            InlineKeyboardButton(
                text="🗑️ Удалить заявку", 
                callback_data=f"mg_order_del:{order_id}:{page}"
            )
        ],
        [InlineKeyboardButton(text="↩️ Назад к списку", 
                              callback_data=f"mg_orders_page:{page}")]
    ])
    
    try:
        await callback.message.edit_text(
            text=text, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        await callback.answer()

@router.callback_query(F.data.startswith("mg_order_approve:"))
async def process_manager_order_approve(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    
    parts = callback.data.split(":")
    order_id = int(parts[1])
    page = int(parts[2])
    
    order = await db_session.get(Order, order_id)
    if order:
        order.status = "approved"  # Переводим статус в 'Выдан'
        await db_session.commit()
        await callback.answer("✅ Статус заказа изменен на 'Выдан'!", show_alert=True)
        
    await render_manager_orders_page(callback, page, db_session)

@router.callback_query(F.data.startswith("mg_order_del:"))
async def process_manager_order_delete(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    
    parts = callback.data.split(":")
    order_id = int(parts[1])
    page = int(parts[2])
    
    order = await db_session.get(Order, order_id)
    if order:
        await db_session.delete(order)
        await db_session.commit()
        await callback.answer("🗑️ Заявка успешно удалена из системы!", show_alert=True)
        
    await render_manager_orders_page(callback, page, db_session)


