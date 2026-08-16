from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_activities_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Отправить сундук сейчас", callback_data="act_send_chest"),
            InlineKeyboardButton(text="🎉 Запустить розыгрыш сейчас", callback_data="act_run_giveaway")
        ],
        [
            InlineKeyboardButton(text="⚙️ Изменить цену ключа", callback_data="act_set_price"),
            InlineKeyboardButton(text="🎖️ Требуемый титул", callback_data="act_set_title")
        ],
        [
            InlineKeyboardButton(text="➕ Добавить награду", callback_data="act_add_reward"),
            InlineKeyboardButton(text="🗑️ Очистить награды", callback_data="act_clear_rewards")
        ]
    ])

def get_titles_choice_keyboard(titles: dict) -> InlineKeyboardMarkup:
    """Генерирует список кнопок со всеми титулами из .env для выбора менеджером."""
    buttons = []
    for t_id, t_info in titles.items():
        buttons.append([InlineKeyboardButton(text=f"🎖️ {t_info.name}", callback_data=f"act_save_title:{t_id}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="act_cancel_settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_reward_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа награды в FSM."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 Валюта рейтинга", callback_data="act_type:rating"),
            InlineKeyboardButton(text="🎒 Физический мерч/товар", callback_data="act_type:physical")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="act_cancel")]
    ])
