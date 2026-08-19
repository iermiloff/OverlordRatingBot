from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.models import OrderStatus

def get_admin_order_keyboard(order_id: int, page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Генерирует инлайн-кнопки управления статусом заказа, навигацию и выход в ЛК."""
    buttons = [
        # Ряд изменения статусов заявки
        [
            InlineKeyboardButton(text="⚙️ В работу", callback_data=f"mg_ord_status:{order_id}:{OrderStatus.PROCESSED.value}:{page}"),
            InlineKeyboardButton(text="✅ Выдано", callback_data=f"mg_ord_status:{order_id}:{OrderStatus.COMPLETED.value}:{page}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mg_ord_status:{order_id}:{OrderStatus.REJECTED.value}:{page}")
        ]
    ]
    
    # Ряд постраничной пагинации очереди
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_orders_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"mg_orders_page:{page+1}"))
        
    if nav_row:
        buttons.append(nav_row)
        
    if page == 1:
        buttons.append([
            InlineKeyboardButton(text="📜 Посмотреть архив выдач", callback_data="mg_orders_archive:1")
        ])
        
    # Кнопка спасения меню от пропадания
    buttons.append([
        InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)
