from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings

def get_user_inline_menu() -> InlineKeyboardMarkup:
    """Генерирует экранное меню для обычного пользователя."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Моя статистика", callback_data="user_stats"),
            InlineKeyboardButton(text="🛍️ Магазин товаров", callback_data="shop_page:1")
        ],
        [
       #     InlineKeyboardButton(text="🤝 Партнерка", callback_data="user_referrals"),
            InlineKeyboardButton(text="🎖️ Список титулов", callback_data="user_titles")
        ],
        [
            InlineKeyboardButton(text="📝 Задания", callback_data="user_tasks"),
            InlineKeyboardButton(text="💬 Наши Чаты", callback_data="user_chats")
        ],
        [
            InlineKeyboardButton(text="🎁 Мои Награды", callback_data="rewards_page:1")
        ]
    ])

def get_manager_inline_menu() -> InlineKeyboardMarkup:
    """Генерирует экранное меню для менеджера."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 Список пользователей", callback_data="mg_users_page:1"),
            InlineKeyboardButton(text="📦 Настройка магазина", callback_data="mg_shop_back")
        ],
        [
            InlineKeyboardButton(text="📥 Заявки/Заказы", callback_data="mg_orders_page:1"),
            InlineKeyboardButton(text="🔒 Антифрод-система", callback_data="af_page:1")
        ],
        [
            InlineKeyboardButton(text="⚙️ Настройка Чатов и Промо", callback_data="mg_settings_panel")
        ],
        [
            InlineKeyboardButton(text="🎁 Сундуки и Розыгрыши", callback_data="mg_activities_panel")
        ]
    ])

def get_back_to_menu_keyboard(to_manager: bool = False) -> InlineKeyboardMarkup:
    """Универсальная кнопка возврата в ЛК для предотвращения тупиков."""
    target = "main_menu_manager" if to_manager else "main_menu_user"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Вернуться в главное меню", callback_data=target)]
    ])
