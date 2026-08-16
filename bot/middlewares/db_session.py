from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from database.connection import AsyncSessionLocal

class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Открываем асинхронную сессию из нашей фабрики
        async with AsyncSessionLocal() as session:
            data["db_session"] = session
            # Передаем управление следующей middleware или хэндлеру
            result = await handler(event, data)
            # Если были изменения, SQLAlchemy применит их сама при закрытии сессии, 
            # но внутри хэндлеров мы будем делать явный commit() для надежности
            return result
