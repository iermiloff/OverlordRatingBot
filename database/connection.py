from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import settings

# Создаем асинхронный движок для работы с PostgreSQL
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Поставь True, если нужно будет видеть чистые SQL-запросы в консоли
    pool_pre_ping=True  # Проверяет живое ли соединение перед отправкой запроса
)

# Фабрика асинхронных сессий
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db_session():
    """Асинхронный генератор сессий БД для использования в хэндлерах и middleware."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
