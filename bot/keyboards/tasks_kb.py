from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_tasks_keyboard(channels: list, completed_ids: set) -> InlineKeyboardMarkup:
    """Генерирует список каналов для подписки."""
    buttons = []
    for ch in channels:
        if ch.id in completed_ids:
            # Если задание уже выполнено, просто показываем текстовую заглушку
            buttons.append([InlineKeyboardButton(text=f"✅ Подписка оформлена (Получено)", callback_data="noop")])
        else:
            # Кнопка перехода в канал и кнопка моментальной проверки
            buttons.append([
                InlineKeyboardButton(text="📢 Перейти в канал", url=ch.invite_link),
                InlineKeyboardButton(text="💎 Проверить", callback_data=f"check_sub:{ch.id}")
            ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_rewards_pagination_keyboard(page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Пагинация для истории наград и заказов."""
    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rewards_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"rewards_page:{page+1}"))
    
    if nav_row:
        buttons.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)
