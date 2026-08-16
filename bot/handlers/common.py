from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import User
from bot.keyboards.menu_kb import get_user_inline_menu, get_manager_inline_menu

router = Router(name="common_router")

@router.message(CommandStart())
async def cmd_start(message: Message, db_user: User):
    """Приветственный хэндлер при команде /start."""
    text = (
        f"🤖 **Добро пожаловать в Личный Кабинет {settings.BOT_NAME}!**\n\n"
        f"Здесь ты можешь отслеживать свою статистику активности в чатах, "
        f"проверять текущий ранг, выполнять партнерские задания и обменивать "
        f"накопленный рейтинг на реальный мерч в нашем магазине! 🛍️\n\n"
        f"Выбери нужный раздел на панели ниже:"
    )
    
    # Проверяем права менеджера
    if message.from_user.id in settings.managers_list:
        await message.answer(
            f"👑 **Вы вошли как менеджер системы!**\n\nВам доступен расширенный пульт CRM управления экономикой чатов:", 
            reply_markup=get_manager_inline_menu()
        )
    else:
        await message.answer(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")


@router.callback_query(F.data == "main_menu_user")
async def back_to_user_menu(callback: CallbackQuery):
    """Бесшовный возврат пользователя в главное меню (с защитой от фото-карточек)."""
    text = f"🤖 **Главное меню личного кабинета:**\n\nВыбери интересующий тебя раздел экономики:"
    
    # ЗАЩИТА: Проверяем, есть ли у сообщения медиа-файлы (фото / анимация)
    if callback.message.photo or callback.message.animation:
        # Если карточка была с картинкой — удаляем её и шлем меню новым сообщением
        await callback.message.answer(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")
        try:
            await callback.message.delete()
        except Exception:
            pass
    else:
        # Если это был обычный текст — бесшовно перерисовываем старый экран
        try:
            await callback.message.edit_text(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")
        except Exception:
            await callback.message.answer(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "main_menu_manager")
async def back_to_manager_menu(callback: CallbackQuery, is_manager: bool):
    """Бесшовный возврат менеджера в главное меню админки."""
    if not is_manager:
        return
        
    text = f"👑 **Главное меню панели управления CRM:**"
    
    if callback.message.photo or callback.message.animation:
        await callback.message.answer(text, reply_markup=get_manager_inline_menu())
        try:
            await callback.message.delete()
        except Exception:
            pass
    else:
        try:
            await callback.message.edit_text(text, reply_markup=get_manager_inline_menu())
        except Exception:
            await callback.message.answer(text, reply_markup=get_manager_inline_menu())
    await callback.answer()



