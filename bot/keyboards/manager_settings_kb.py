from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_settings_main_keyboard(chats: list) -> InlineKeyboardMarkup:
    """Генерирует пульт управления чатами и кнопку добавления промо."""
    buttons = []
    
    # Сначала выводим список чатов и их текущий статус
    for chat in chats:
        status_emoji = "✅" if chat.is_active else "❌"
        buttons.append([
            InlineKeyboardButton(
                text=f"{status_emoji} {chat.title}", 
                callback_data=f"mg_chat_toggle:{chat.id}"
            )
        ])
        
    # Кнопка добавления нового партнерского задания
    buttons.append([
        InlineKeyboardButton(text="➕ Добавить промо-канал", callback_data="mg_promo_add")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
