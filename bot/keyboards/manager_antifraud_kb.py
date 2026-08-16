from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_antifraud_actions_keyboard(user_id: int, page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Генерирует сетку кнопок для принятия мер к подозрительному пользователю."""
    buttons = [
        [
            InlineKeyboardButton(text="💎 Снять рейтинг", callback_data=f"af_act:{user_id}:strip:{page}"),
            InlineKeyboardButton(text="✅ Оставить как есть", callback_data=f"af_act:{user_id}:clear:{page}")
        ],
        [
            InlineKeyboardButton(text="⏳ Бан на 7 дней", callback_data=f"af_act:{user_id}:ban_temp:{page}"),
            InlineKeyboardButton(text="⛔ Бан навсегда", callback_data=f"af_act:{user_id}:ban_perm:{page}")
        ]
    ]
    
    # Ряд навигации по списку нарушителей
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"af_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"af_page:{page+1}"))
        
    if nav_row:
        buttons.append(nav_row)
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)
