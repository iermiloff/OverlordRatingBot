from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

# Прямые импорты моделей и клавиатур
from database.models import Order, OrderStatus, User
from bot.keyboards.manager_orders_kb import get_admin_order_keyboard

router = Router(name="manager_orders_router")

ORDERS_PER_PAGE = 1

# --- 📥 БЕЗОПАСНЫЙ ВЫВОД СТРАНИЦЫ ЗАЯВОК И ЗАКАЗОВ ---

async def render_manager_orders_page(
    callback: CallbackQuery, 
    page: int, 
    db_session: AsyncSession
):
    """Строгая функция отрисовки заказов с постраничной пагинацией."""
    limit = 5
    offset = (page - 1) * limit
    
    # Считаем общее количество активных заявок мерча
    count_q = select(func.count(Order.id))
    total = (await db_session.execute(count_q)).scalar() or 0
    
    # Выгружаем список заказов для текущей страницы
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
        
    # Формируем навигационную панель стрелок
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


@router.callback_query(F.data.startswith("mg_orders_page:"))
async def process_manager_orders_page_click(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Перехват клика по кнопке Заказов с безопасным разбором страницы."""
    if not is_manager: return
    
    # Извлекаем номер страницы из данных кнопки (например, из 'mg_orders_page:1')
    page = int(callback.data.split(":")[1])
    
    await render_manager_orders_page(
        callback=callback,
        page=page,
        db_session=db_session
    )

@router.callback_query(F.data.startswith("mg_ord_status:"))
async def process_mg_order_status_change(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager:
        return
    
    # ИСПРАВЛЕНО: безопасный разбор параметров по точным индексам split
    parts = callback.data.split(":")
    order_id = int(parts[1])
    new_status_val = parts[2]
    page = int(parts[3])
    
    new_status = OrderStatus(new_status_val)

    order = await db_session.get(Order, order_id)
    if not order:
        await callback.answer("❌ Заказ не найден.", show_alert=True)
        await send_admin_orders_page(callback, db_session, page=1)
        return

    # Обновляем статус в базе данных PostgreSQL
    order.status = new_status
    await db_session.commit()

    # Формируем и отправляем push-уведомление выигравшему/покупателю
    status_notifications = {
        OrderStatus.PROCESSED: f"⚙️ Ваш заказ *'{order.item_name}'* взят менеджером в обработку.",
        OrderStatus.COMPLETED: f"🎉 Ваш order *'{order.item_name}'* успешно выдан или отправлен! Проверьте в ЛК.",
        OrderStatus.REJECTED: f"❌ Ваш заказ *'{order.item_name}'* был отклонен менеджером. Обратитесь в техподдержку."
    }
    
    try:
        await callback.bot.send_message(
            chat_id=order.user_id,
            text=status_notifications.get(new_status),
            parse_mode="Markdown"
        )
    except Exception:
        pass  # Игнорируем, если пользователь заблокировал бота

    await callback.answer(f"✅ Статус заказа №{order_id} успешно изменен!")
    
    # Перерисовываем страницу. Закрытые заказы автоматически исчезнут из этой выборки
    await send_admin_orders_page(callback, db_session, page=page)

