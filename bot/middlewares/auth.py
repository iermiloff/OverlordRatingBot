from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Прямые импорты из корня и базы
from config import settings
from database.models import User

class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_tg = None
        if isinstance(event, Message):
            user_tg = event.from_user
        elif isinstance(event, CallbackQuery):
            user_tg = event.from_user

        if not user_tg or user_tg.is_bot:
            return await handler(event, data)

        session: AsyncSession = data.get("db_session")
        if not session:
            return await handler(event, data)

        # Ищем пользователя в базе данных
        result = await session.execute(select(User).where(User.tg_id == user_tg.id))
        user = result.scalar_one_or_none()

        # Если пользователя нет — регистрируем его
        if not user:
            user = User(
                tg_id=user_tg.id,
                username=user_tg.username,
                full_name=user_tg.full_name or user_tg.first_name
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        # Если пользователь забанен — прекращаем обработку
        if user.is_banned:
            if isinstance(event, Message):
                await event.answer("⛔ Ваш аккаунт заблокирован менеджером.")
            return

        # ЯВНО записываем данные в словарь data для передачи в хэндлеры
        data["db_user"] = user
        data["is_manager"] = user_tg.id in settings.managers_list

        # Возвращаем выполнение следующего звена с модифицированным data
        return await handler(event, data)

