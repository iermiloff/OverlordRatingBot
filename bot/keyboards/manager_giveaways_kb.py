from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_giveaways_main_keyboard(has_active: bool) -> InlineKeyboardMarkup:
    """Главный пульт управления розыгрышами."""
    buttons = []
    if has_active:
        buttons.append([InlineKeyboardButton(text="🛑 Подвести итоги розыгрыша", callback_data="ga_finalize")])
    else:
        buttons.append([InlineKeyboardButton(text="➕ Создать новый розыгрыш", callback_data="ga_create")])
        
    buttons.append([InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_ga_reward_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор приза лотереи."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 Валюта рейтинга", callback_data="ga_type:rating"),
            InlineKeyboardButton(text="🎒 Физический мерч", callback_data="ga_type:physical")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="ga_cancel")]
    ])

def get_ga_condition_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор условия входа."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎖️ Ограничение по Титулу", callback_data="ga_cond:title"),
            InlineKeyboardButton(text="🎟️ Вход по Билету", callback_data="ga_cond:ticket")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="ga_cancel")]
    ])

def get_ga_tickets_keyboard(tickets: list) -> InlineKeyboardMarkup:
    """Выводит список созданных в магазине билетов для привязки к розыгрышу."""
    buttons = []
    for t in tickets:
        buttons.append([InlineKeyboardButton(text=f"🎟️ {t.name}", callback_data=f"ga_save_cond_ticket:{t.id}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ga_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
