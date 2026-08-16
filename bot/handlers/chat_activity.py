from aiogram import Router
from aiogram.types import Message

router = Router(name="chat_activity_router")

# Хэндлер ловит абсолютно любые текстовые сообщения в группах
@router.message()
async def handle_group_message(message: Message):
    # Вся логика выполняется на уровне Middleware (ActivityLogMiddleware).
    # Хэндлер остается пустым, чтобы не спамить в чат ответами на каждое сообщение.
    pass
