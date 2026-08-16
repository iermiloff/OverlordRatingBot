from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_settings_main_keyboard(chats: list, promo_channels: list) -> InlineKeyboardMarkup:
    """
    Генерирует пульт управления чатами и промо-каналами.
    Принимает списки объектов из базы данных.
    """
    buttons = []
    
    # 1. Секция модерирования чатов активности
    for chat in chats:
        status_emoji = "✅" if chat.is_active else "❌"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status_emoji} Чат: {chat.title}", 
                callback_data=f"mg_chat_toggle:{chat.id}"
            )
        ])
        
    # 2. Секция существующих партнерских ссылок с кнопками удаления
    for promo in promo_channels:
        buttons.append([
            InlineKeyboardButton(text=f"📢 ID: {promo.id}", url=promo.invite_link),
            InlineKeyboardButton(text="🗑️ Удалить промо", callback_data=f"mg_promo_del:{promo.id}")
        ])
        
    # 3. Кнопка создания нового задания на подписку
    buttons.append([
        InlineKeyboardButton(text="➕ Добавить промо-канал", callback_data="mg_promo_add")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)
