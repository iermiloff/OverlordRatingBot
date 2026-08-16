import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.models import User, ActivityLog, ChatConfig
from services.rating import process_user_activity

class ActivityLogMiddleware(BaseMiddleware):
    def __init__(self):
        # Локальный кэш кулдауна начислений в ОЗУ (User_ID -> Timestamp)
        self.cooldowns: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # ЗАЩИТА: Если это не сообщение или сообщение отправлено в ЛС боту (private) —
        # мы вообще ничего не делаем и мгновенно передаем управление дальше
        if not isinstance(event, Message) or event.chat.type == "private":
            return await handler(event, data)

        # Пропускаем, если текста нет
        if not event.text:
            return await handler(event, data)

        session: AsyncSession = data.get("db_session")
        db_user: User = data.get("db_user")
        
        if not session or not db_user:
            return await handler(event, data)

        # 1. Проверяем, включен ли чат менеджером
        chat_check = await session.execute(
            select(ChatConfig).where(ChatConfig.id == event.chat.id)
        )
        chat_config = chat_check.scalar_one_or_none()
        
        if not chat_config:
            chat_config = ChatConfig(id=event.chat.id, title=event.chat.title or "Группа")
            session.add(chat_config)
            await session.commit()
        
        if not chat_config.is_active:
            return await handler(event, data)

        # 2. Логируем для анти-фрода
        raw_log = ActivityLog(
            user_id=event.from_user.id,
            chat_id=event.chat.id,
            message_length=len(event.text)
        )
        session.add(raw_log)
        await session.commit()

        # 3. Экономика и кулдауны
        now = time.time()
        user_id = event.from_user.id
        last_earned = self.cooldowns.get(user_id, 0.0)

        if now - last_earned >= settings.COOLDOWN_MESSAGE_SEC:
            success = await process_user_activity(session, db_user, len(event.text))
            if success:
                self.cooldowns[user_id] = now

        return await handler(event, data)
