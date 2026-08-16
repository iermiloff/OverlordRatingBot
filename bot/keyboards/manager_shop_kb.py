from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings

def get_manager_shop_keyboard(items: list) -> InlineKeyboardMarkup:
    """Генерирует список товаров для менеджера с кнопкой добавления и ВЫХОДА."""
    buttons = []
    
    for item in items:
        buttons.append([
            InlineKeyboardButton(text=f"📦 {item.name} ({item.price} {settings.CURRENCY_NAME})", 
                                 callback_data=f"mg_shop_view:{item.id}")
        ])
        
    buttons.append([InlineKeyboardButton(text="➕ Добавить новый товар", callback_data="mg_shop_add")])
    
    # ИСПРАВЛЕНО: Кнопка возврата в корень админки
    buttons.append([InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_item_admin_keyboard(item_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления конкретным товаром."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Удалить товар из магазина", callback_data=f"mg_shop_del:{item_id}")],
        [InlineKeyboardButton(text="↩️ Назад к ассортименту", callback_data="mg_shop_back")]
    ])

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены создания на любом шаге FSM."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить создание", callback_data="mg_shop_cancel")]
    ])

def get_item_type_choice_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора: является ли создаваемый товар лотерейным билетом."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎒 Обычный мерч / товар", callback_data="mg_type:merch"),
            InlineKeyboardButton(text="🎟️ Лотерейный билет", callback_data="mg_type:ticket")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="mg_shop_cancel")]
    ])
