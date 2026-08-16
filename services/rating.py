from sqlalchemy.ext.asyncio import AsyncSession
from config import settings
from database.models import User

async def process_user_activity(session: AsyncSession, db_user: User, text_length: int) -> bool:
    """
    Основной бизнес-метод обработки активности.
    Начисляет рейтинг, проверяет условия рефералов и апгрейдит титул.
    Возвращает True, если рейтинг был начислен.
    """
    # Защитный слой: если длина текста меньше лимита из .env — пропускаем
    if text_length < settings.MIN_MESSAGE_LENGTH_FOR_RATING:
        return False

    # Сохраняем старое значение общего рейтинга для реферальной проверки
    old_lifetime_rating = db_user.lifetime_rating

    # Начисляем базовый рейтинг из конфига Whitelabel
    reward = settings.RATING_PER_MESSAGE
    db_user.current_rating += reward
    db_user.lifetime_rating += reward

    # --- ПРОВЕРКА РЕФЕРАЛЬНОЙ СИСТЕМЫ ---
    # Если пользователя кто-то пригласил, и награда за него ЕЩЕ НЕ БЫЛА ВЫПЛАЧЕНА,
    # и именно в это начисление он пересек рубеж (например, 200 поинтов)
    if (db_user.referrer_id and 
        not db_user.is_ref_reward_paid and 
        old_lifetime_rating < settings.REF_TARGET_RATING <= db_user.lifetime_rating):
        
        # Находим реферера (пригласившего) и начисляем ему бонус
        from sqlalchemy import select
        ref_result = await session.execute(
            select(User).where(User.tg_id == db_user.referrer_id)
        )
        referrer = ref_result.scalar_one_or_none()
        
        if referrer:
            referrer.current_rating += settings.REF_REWARD_RATING
            referrer.lifetime_rating += settings.REF_REWARD_RATING
            db_user.is_ref_reward_paid = True

    await session.commit()
    return True

def get_user_title_name(lifetime_rating: int) -> str:
    """
    Определяет текущее текстовое имя титула на основе несгораемого lifetime_rating.
    Парсит конфигурацию TITLES_CONFIG из .env на лету.
    """
    titles = settings.parsed_titles
    if not titles:
        return "Без титула"

    # Сортируем титулы по убыванию порога рейтинга
    sorted_titles = sorted(titles.values(), key=lambda x: x.min_rating, reverse=True)
    
    for title in sorted_titles:
        if lifetime_rating >= title.min_rating:
            return title.name
            
    return "Новичок"
