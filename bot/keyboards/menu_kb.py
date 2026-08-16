from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from config import settings

def get_user_keyboard() -> ReplyKeyboardMarkup:
    """Генерирует главное меню для обычного пользователя."""
    keyboard = [
        [KeyboardButton(text="📊 Моя статистика"), KeyboardButton(text="🛍️ Магазин товаров")],
        #[KeyboardButton(text="🤝 Партнерская программа")], 
        [KeyboardButton(text="🎖️ Список титулов")],
        [KeyboardButton(text="📝 Задания"), KeyboardButton(text="💬 Наши Чаты")],
        [KeyboardButton(text="🎁 Мои Награды")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_manager_keyboard() -> ReplyKeyboardMarkup:
    """Генерирует главное меню для менеджера/администратора."""
    keyboard = [
        [KeyboardButton(text="📈 Общая статистика"), KeyboardButton(text="👥 Список пользователей")],
        [KeyboardButton(text="📦 Настройка магазина"), KeyboardButton(text="📥 Заявки/Заказы")],
        [KeyboardButton(text="🎁 Настройка Сундука / Розыгрышей")],
        [KeyboardButton(text="⚙️ Настройка Чатов и Промо"), KeyboardButton(text="🔒 Антифрод-система")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
