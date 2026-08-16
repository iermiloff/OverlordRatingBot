from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Прямые импорты из корня и модулей
from config import settings
from database.models import User
from bot.keyboards.menu_kb import get_user_keyboard, get_manager_keyboard

# Создаем изолированный роутер для общих команд
router = Router(name="common_router")

@router.message(CommandStart())
async def cmd_start(message: Message, db_user: User, is_manager: bool, db_session: AsyncSession):
    """
    Обработчик команды /start.
    Аргументы db_user и is_manager автоматически прилетели из AuthMiddleware.
    """
    # Проверяем, пришел ли пользователь по реферальной ссылке
    # Формат ссылки: t.me/bot?start=ref_12345678
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            # Проверяем, что пользователь не пригласил сам себя 
            # и у него еще не установлен реферер (первый запуск)
            if referrer_id != message.from_user.id and db_user.referrer_id is None:
                # Проверяем, существует ли вообще такой реферер в базе
                ref_check = await db_session.execute(
                    select(User).where(User.tg_id == referrer_id)
                )
                if ref_check.scalar_one_or_none():
                    db_user.referrer_id = referrer_id
                    await db_session.commit()
                    # Примечание: начисление рейтинга рефереру произойдет позже,
                    # когда этот реферал наберет лимит (например, 200 рейтинга).
        except ValueError:
            pass # Игнорируем некорректный ID в ссылке

    # Разделение интерфейсов на основе роли
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
async def cmd_menu(message: Message, is_manager: bool):
    """Команда /menu на случай, если у пользователя пропала клавиатура."""
    if is_manager:
        await message.answer("🎛️ Главное меню менеджера:", reply_markup=get_manager_keyboard())
    else:
        await message.answer("📱 Твое главное меню:", reply_markup=get_user_keyboard())
