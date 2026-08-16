from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_activities_main_keyboard() -> InlineKeyboardMarkup:
    """Главный пульт управления активностями чата."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📦 Отправить сундук сейчас", callback_data="act_send_chest"),
            InlineKeyboardButton(text="🎉 Запустить розыгрыш сейчас", callback_data="act_run_giveaway")
        ],
        [
            InlineKeyboardButton(text="➕ Добавить награду в сундук", callback_data="act_add_reward"),
            InlineKeyboardButton(text="🗑️ Очистить все награды", callback_data="act_clear_rewards")
        ]
    ])

def get_reward_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа награды в FSM."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 Валюта рейтинга", callback_data="act_type:rating"),
            InlineKeyboardButton(text="🎒 Физический мерч/товар", callback_data="act_type:physical")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="act_cancel")]
    ])
