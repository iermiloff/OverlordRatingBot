import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# Прямые импорты из корня проекта
from config import settings
from database.connection import engine
from database.models import Base

# Импорты Middlewares
from bot.middlewares.db_session import DbSessionMiddleware
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.activity_log import ActivityLogMiddleware

# Импортируем централизованный сборщик роутеров
from bot.handlers import get_main_router

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

async def init_db():
    """Автоматически создает все таблицы в базе данных при старте с механизмом ожидания."""
    logger.info("Инициализация базы данных...")
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("База данных успешно инициализирована!")
            return
        except Exception as e:
            if attempt == max_retries:
                logger.error("❌ Не удалось подключиться к базе данных.")
                raise e
            logger.warning(f"⚠️ База данных еще не готова (Попытка {attempt}/{max_retries}). Ожидание 2 секунды...")
            await asyncio.sleep(2)

async def main():
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # 1. Инициализация структуры БД
    await init_db()

    # 2. Подключение OUTER Middlewares (выполняются до FSM и фильтров роутеров)
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(AuthMiddleware())

    # 3. Подключение INNER Middleware (выполняется только для текстовых сообщений)
    dp.message.middleware(ActivityLogMiddleware())

    # 4. Подключаем единый собранный роутер со всеми хэндлерами
    dp.include_router(get_main_router())

    logger.info(f"Запуск бота {settings.BOT_NAME} в режиме Polling...")
    
    try:
        # Очищаем очередь сообщений, пришедших в офлайне
        await bot.delete_webhook(drop_pending_updates=True)
        # Запускаем бесконечный асинхронный цикл прослушивания Telegram
        await dp.start_polling(bot)
    finally:
        # Корректно закрываем сессию бота при остановке контейнера
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())

