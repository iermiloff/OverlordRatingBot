from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_settings_main_keyboard(chats: list, promo_channels: list) -> InlineKeyboardMarkup:
    """
    Генерирует экранный пульт управления чатами и промо-каналами.
    Принимает списки объектов из базы данных.
    """
    buttons = []
    
    # 1. Секция модерирования чатов активности (включен / выключен)
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
    
    # 4. Кнопка возврата в главное меню админки
    buttons.append([
        InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

import pytz
from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_timezone_selection_keyboard() -> InlineKeyboardMarkup:
    """Генерирует сетку смещений UTC с динамическим показом текущего времени на кнопках."""
    buttons = []
    now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)

    # Карта основных регионов для наглядности
    tz_mapping = [
        ("London (UTC+0)", "UTC"),
        ("Europe/Belgrade (UTC+1)", "Europe/Belgrade"),
        ("Kyiv/Kaliningrad (UTC+2)", "Europe/Kyiv"),
        ("Moscow/Minsk (UTC+3)", "Europe/Moscow"),
        ("Samara/Baku (UTC+4)", "Europe/Samara"),
        ("Yekaterinburg (UTC+5)", "Europe/Yekaterinburg"),
        ("Omsk/Astana (UTC+6)", "Europe/Omsk"),
        ("Novosibirsk/Krasnoyarsk (UTC+7)", "Europe/Novosibirsk"),
        ("Bali/Singapore (UTC+8)", "Asia/Makassar"),
        ("Tokyo/Yakutsk (UTC+9)", "Asia/Tokyo"),
        ("Vladivostok (UTC+10)", "Asia/Vladivostok"),
        ("Magadan (UTC+11)", "Asia/Magadan"),
        ("Kamchatka (UTC+12)", "Asia/Kamchatka"),
        ("New York (UTC-5)", "America/New_York"),
        ("Los Angeles (UTC-8)", "America/Los_Angeles")
    ]

    row = []
    for label, tz_name in tz_mapping:
        try:
            tz = pytz.timezone(tz_name)
            localized_time = now_utc.astimezone(tz)
            time_str = localized_time.strftime("%H:%M")
            
            # На кнопке пишем название региона и сколько там СЕЙЧАС времени
            button_text = f"🌐 {label} ➔ ⏰ {time_str}"
            row.append(InlineKeyboardButton(text=button_text, callback_data=f"set_profile_tz:{tz_name}"))
            
            if len(row) == 1:  # Выводим по одной большой кнопке в ряд для идеальной читаемости на смартфонах
                buttons.append(row)
                row = []
        except Exception:
            continue

    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="❌ Назад в настройки", callback_data="mg_settings_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
