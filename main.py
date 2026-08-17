import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import text

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

async def init_db():
    """Автоматически создает таблицы и обновляет структуру старых таблиц при старте."""
    logger.info("Инициализация базы данных...")
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            # 1. Создаем новые таблицы, если их нет
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            # 2. Накатываем обновление для старой таблицы chats_config (добавляем invite_link)
            async with engine.connect() as conn:
                await conn.execute(
                    text("ALTER TABLE chats_config ADD COLUMN IF NOT EXISTS invite_link VARCHAR(256);")
                )
                await conn.commit()
                
            logger.info("База данных успешно инициализирована и обновлена!")
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

    # 2. Регистрируем сессию БД и авторизацию для ОБЫЧНЫХ СООБЩЕНИЙ
    dp.message.middleware(DbSessionMiddleware())
    dp.message.middleware(AuthMiddleware())

    # 3. Регистрируем сессию БД и авторизацию для НАЖАТИЙ ИНЛАЙН-КНОПОК
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    from bot.middlewares.antifraud_math import AntiFraudMathMiddleware
    dp.message.middleware(AntiFraudMathMiddleware())
    
    dp.message.middleware(ActivityLogMiddleware())

    # 5. Подключаем единый собранный роутер со всеми хэндлерами
    dp.include_router(get_main_router())

    from services.scheduler import start_scheduler
    start_scheduler(bot)

    logger.info(f"Запуск бота {settings.BOT_NAME} в режиме Polling...")
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())


