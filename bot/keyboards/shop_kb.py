from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_shop_item_keyboard(item_id: int, page: int, has_next: bool, price: int) -> InlineKeyboardMarkup:
    """Генерирует инлайн-кнопки управления карточкой товара."""
    buttons = []
    
    # Ряд навигации (Назад / Вперед)
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"shop_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"shop_page:{page+1}"))
    
    if nav_row:
        buttons.append(nav_row)
        
    # Кнопка покупки конкретного товара
    buttons.append([
        InlineKeyboardButton(text=f"🛒 Купить за {price}", callback_data=f"shop_buy:{item_id}:{page}")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_order_confirm_keyboard(item_id: int) -> InlineKeyboardMarkup:
    """Кнопки подтверждения покупки после ввода данных доставки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Всё верно, отправить заказ", callback_data=f"order_confirm:{item_id}")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="order_cancel")]
    ])
