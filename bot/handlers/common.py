from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.models import User
from bot.keyboards.menu_kb import get_user_keyboard, get_manager_keyboard

router = Router(name="common_router")

@router.message(CommandStart())
async def cmd_start(message: Message, db_user: User, db_session: AsyncSession):
    """Обработчик команды /start."""
    # Проверяем, является ли пользователь менеджером
    is_manager = message.from_user.id in settings.managers_list

    # Обработка реферального хвоста ссылки
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id != message.from_user.id and db_user.referrer_id is None:
                ref_check = await db_session.execute(
                    select(User).where(User.tg_id == referrer_id)
                )
                if ref_check.scalar_one_or_none():
                    db_user.referrer_id = referrer_id
                    await db_session.commit()
        except ValueError:
            pass

    # Выдача ЛК на основе роли
    if is_manager:
        await message.answer(
            f"⚡ Добро пожаловать в панель управления {settings.BOT_NAME}!\n"
            f"Вы авторизованы как **Менеджер**.\n\n"
            f"Используйте нижнее меню для настройки магазина, сундуков и работы с пользователями.",
            reply_markup=get_manager_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"👋 Приветствуем в {settings.BOT_NAME}!\n\n"
            f"Здесь ты можешь проявлять активность в наших чатах, получать за это "
            f"валюту {settings.CURRENCY_EMOJI} {settings.CURRENCY_NAME}, "
            f"открывать новые титулы и тратить баланс в магазине мерча!",
            reply_markup=get_user_keyboard()
        )

@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Команда /menu для восстановления клавиатуры."""
    is_manager = message.from_user.id in settings.managers_list
    if is_manager:
        await message.answer("🎛️ Главное меню менеджера:", reply_markup=get_manager_keyboard())
    else:
        await message.answer("📱 Твое главное меню:", reply_markup=get_user_keyboard())

