from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.models import User
from bot.keyboards.menu_kb import get_user_inline_menu, get_manager_inline_menu

router = Router(name="common_router")

def get_welcome_text(user_name: str, is_manager: bool) -> str:
    if is_manager:
        return (
            f"⚡ **Панель управления {settings.BOT_NAME}**\n"
            f"Роль: **Менеджер**\n\n"
            f"Используйте экранные кнопки ниже для управления экономикой, "
            f"просмотра нарушителей и выдачи заказов."
        )
    return (
        f"👋 **Добро пожаловать в {settings.BOT_NAME}!**\n\n"
        f"Проявляй активность в наших чатах, зарабатывай {settings.CURRENCY_EMOJI} {settings.CURRENCY_NAME}, "
        f"открывай титулы и покупай мерч!"
    )

@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, db_user: User, db_session: AsyncSession):
    is_manager = message.from_user.id in settings.managers_list
    text = get_welcome_text(message.from_user.first_name, is_manager)
    kb = get_manager_inline_menu() if is_manager else get_user_inline_menu()
    
    # Отправляем чистое сообщение с инлайн кнопками
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "main_menu_user")
async def back_to_user_menu(callback: CallbackQuery):
    text = get_welcome_text(callback.from_user.first_name, is_manager=False)
    await callback.message.edit_text(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "main_menu_manager")
async def back_to_manager_menu(callback: CallbackQuery):
    text = get_welcome_text(callback.from_user.first_name, is_manager=True)
    await callback.message.edit_text(text, reply_markup=get_manager_inline_menu(), parse_mode="Markdown")
    await callback.answer()


