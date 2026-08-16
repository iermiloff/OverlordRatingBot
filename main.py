import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# Прямые импорты из корня проекта
from config import settings
from database.connection import engine
from database.models import Base

from bot.middlewares.db_session import DbSessionMiddleware
from bot.middlewares.auth.py import AuthMiddleware  # убираем .py, пишем просто auth
from bot.middlewares.auth import AuthMiddleware
from bot.handlers.common import router as common_router
from bot.middlewares.activity_log import ActivityLogMiddleware
from bot.handlers.chat_activity import router as chat_activity_router
from bot.handlers.user_lk import router as user_lk_router
from bot.handlers.shop_user import router as shop_user_router
from bot.handlers.user_tasks import router as user_tasks_router
from bot.handlers.manager_users import router as manager_users_router
from bot.handlers.manager_shop import router as manager_shop_router
from bot.handlers.manager_orders import router as manager_orders_router
from bot.handlers.manager_antifraud import router as manager_antifraud_router
from bot.handlers.manager_activities import router as manager_activities_router
from bot.handlers.manager_settings import router as manager_settings_router


# Настраиваем логирование, чтобы видеть состояние бота в консоли
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

async def init_db():
    """Автоматически создает все таблицы в базе данных при старте."""
    logger.info("Инициализация базы данных...")
    async with engine.begin() as conn:
        # Эта строчка создаст таблицы на основе моделей из database/models.py
        await conn.run_sync(Base.metadata.create_all)
    logger.info("База данных успешно инициализирована!")

async def main():
    # Создаем объект бота, передавая токен из нашего Whitelabel конфига
    bot = Bot(token=settings.BOT_TOKEN)
    
    # Инициализируем диспетчер и включаем хранилище в оперативной памяти для FSM (сценариев)
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(DbSessionMiddleware())
    dp.update.middleware(AuthMiddleware())
    # Вызываем создание таблиц перед запуском бота
    await init_db()

    logger.info(f"Запуск бота {settings.BOT_NAME} в режиме Polling...")
    
    try:
        # Стираем все сообщения, которые пришли боту, пока он был выключен (чтобы не спамил старым)
        await bot.delete_webhook(drop_pending_updates=True)
    dp.message.middleware(ActivityLogMiddleware())
    dp.include_router(common_router)
    dp.include_router(user_lk_router)
    dp.include_router(shop_user_router)
    dp.include_router(user_tasks_router)
    dp.include_router(manager_users_router)
    dp.include_router(manager_shop_router)
    dp.include_router(manager_orders_router)
    dp.include_router(manager_antifraud_router)
    dp.include_router(manager_activities_router)
    dp.include_router(manager_settings_router)
    dp.include_router(chat_activity_router)
        # Запускаем бесконечный цикл обработки обновлений
        await dp.start_polling(bot)
    finally:
        # Корректно закрываем сессию бота при остановке контейнера
        await bot.session.close()

if __name__ == "__main__":
    # Запуск асинхронного ядра Python
    asyncio.run(main())
