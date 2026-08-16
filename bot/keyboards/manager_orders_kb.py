from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.models import OrderStatus

def get_admin_order_keyboard(order_id: int, page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Генерирует инлайн-кнопки переключения статусов и пагинации заказа."""
    buttons = [
        # Первый ряд: смена статусов
        [
            InlineKeyboardButton(text="⚙️ В работу", callback_data=f"mg_ord_status:{order_id}:{OrderStatus.PROCESSED.value}:{page}"),
            InlineKeyboardButton(text="✅ Выдано", callback_data=f"mg_ord_status:{order_id}:{OrderStatus.COMPLETED.value}:{page}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mg_ord_status:{order_id}:{OrderStatus.REJECTED.value}:{page}")
        ]
    ]
    
    # Второй ряд: навигация по страницам заявок
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_orders_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"mg_orders_page:{page+1}"))
        
    if nav_row:
        buttons.append(nav_row)
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)
