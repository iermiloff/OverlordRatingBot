from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_users_list_keyboard(users: list, page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Список пользователей в виде кнопок для выбора."""
    buttons = []
    
    # Кнопка на каждого юзера
    for u in users:
        username_text = f" (@{u.username})" if u.username else ""
        buttons.append([
            InlineKeyboardButton(text=f"👤 {u.full_name}{username_text}", callback_data=f"mg_user_view:{u.tg_id}:{page}")
        ])
        
    # Ряд навигации
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_users_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"mg_users_page:{page+1}"))
        
    if nav_row:
        buttons.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_user_profile_keyboard(user_id: int, page: int) -> InlineKeyboardMarkup:
    """Действия внутри карточки конкретного пользователя."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Изменить баланс рейтинга", callback_data=f"mg_user_rate:{user_id}:{page}")],
        [InlineKeyboardButton(text="🎁 Выдать товар (Подарок)", callback_data=f"mg_user_gift:{user_id}:{page}")],
        [InlineKeyboardButton(text="↩️ Назад к списку", callback_data=f"mg_users_page:{page}")]
    ])

def get_gift_items_keyboard(items: list, user_id: int, page: int) -> InlineKeyboardMarkup:
    """Список товаров для бесплатной выдачи."""
    buttons = []
    for item in items:
        buttons.append([
            InlineKeyboardButton(text=f"📦 {item.name} ({item.price} {settings.CURRENCY_NAME})", 
                                 callback_data=f"mg_gift_confirm:{user_id}:{item.id}:{page}")
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"mg_user_view:{user_id}:{page}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
