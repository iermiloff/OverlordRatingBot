from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

# Прямые импорты из корня и модулей
from config import settings
from database.models import User
from services.rating import get_user_title_name

router = Router(name="user_lk_router")

@router.message(F.text == "📊 Моя статистика")
async def show_user_stats(message: Message, db_user: User, db_session: AsyncSession):
    """Выводит текущие балансы, титул и позицию пользователя в глобальном топе."""
    # Вычисляем позицию в топе по несгораемому lifetime_rating
    # Считаем, сколько людей имеют рейтинг строго больше, чем у текущего юзера, и прибавляем 1
    rank_query = select(func.count(User.tg_id)).where(User.lifetime_rating > db_user.lifetime_rating)
    rank_result = await db_session.execute(rank_query)
    user_rank = rank_result.scalar() + 1

    # Получаем текстовое имя титула
    title_name = get_user_title_name(db_user.lifetime_rating)

    text = (
        f"📊 **Твоя статистика в {settings.BOT_NAME}**\n\n"
        f"👤 Пользователь: {message.from_user.mention_html()}\n"
        f"🎖️ Текущий титул: **{title_name}**\n"
        f"🏆 Место в глобальном рейтинге: **#{user_rank}**\n\n"
        f"💳 Доступный баланс: {settings.CURRENCY_EMOJI} **{db_user.current_rating} {settings.CURRENCY_NAME}**\n"
        f"📈 Всего заработано за всё время: {settings.CURRENCY_EMOJI} **{db_user.lifetime_rating} {settings.CURRENCY_NAME}**\n\n"
        f"ℹ️ _Трать доступный баланс в магазине, твой титул и место в топе от этого не изменятся!_"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🤝 Партнерская программа")
async def show_referral_program(message: Message, db_user: User, db_session: AsyncSession):
    """Выводит реферальную ссылку и детальную разбивку по приглашенным."""
    bot_info = await message.bot.get_me()
    # Формируем уникальную диплинк-ссылку для отслеживания
    ref_link = f"https://t.me{bot_info.username}?start=ref_{db_user.tg_id}"

    # Делаем три быстрых COUNT-запроса в рамках одной сессии
    # 1. Всего приглашено
    all_ref_q = select(func.count(User.tg_id)).where(User.referrer_id == db_user.tg_id)
    all_ref = (await db_session.execute(all_ref_q)).scalar()

    # 2. В ожидании (кто еще не набрал нужный порог рейтинга)
    pending_ref_q = select(func.count(User.tg_id)).where(
        User.referrer_id == db_user.tg_id,
        User.lifetime_rating < settings.REF_TARGET_RATING
    )
    pending_ref = (await db_session.execute(pending_ref_q)).scalar()

    # 3. Успешные (кто набрал порог и за кого начислена награда)
    success_ref_q = select(func.count(User.tg_id)).where(
        User.referrer_id == db_user.tg_id,
        User.lifetime_rating >= settings.REF_TARGET_RATING
    )
    success_ref = (await db_session.execute(success_ref_q)).scalar()

    # Считаем суммарный доход от рефералов
    total_earned = success_ref * settings.REF_REWARD_RATING

    text = (
        f"🤝 **Партнерская программа**\n\n"
        f"Приглашай друзей и зарабатывай {settings.CURRENCY_EMOJI} **{settings.REF_REWARD_RATING} {settings.CURRENCY_NAME}** "
        f"за каждого, кто проявит активность!\n\n"
        f"💵 Награда начислится, когда твой друг наберет **{settings.REF_TARGET_RATING}** очков общего рейтинга.\n\n"
        f"🔗 **Твоя реферальная ссылка:**\n<code>{ref_link}</code>\n\n"
        f"📊 **Статистика приглашений:**\n"
        f"▪️ Всего приглашено человек: **{all_ref}**\n"
        f"▪️ В ожидании активации: **{pending_ref}**\n"
        f"▪️ Успешные рефералы: **{success_ref}**\n"
        f"💰 Всего заработано на рефералах: **{total_earned} {settings.CURRENCY_NAME}**"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🎖️ Список титулов")
async def show_titles_list(message: Message, db_user: User):
    """Выводит красивую иерархию титулов из .env и показывает прогресс текущего юзера."""
    # Получаем распарсенный из .env словарь классов TitleInfo
    titles_config = settings.parsed_titles
    if not titles_config:
        await message.answer("📭 Список титулов временно не настроен.")
        return

    # Сортируем титулы строго по возрастанию порога рейтинга
    sorted_titles = sorted(titles_config.values(), key=lambda x: x.min_rating)
    
    current_title_name = get_user_title_name(db_user.lifetime_rating)

    lines = ["🎖️ **Иерархия доступных титулов:**\n"]
    next_title = None

    for title in sorted_titles:
        # Ставим маркер-галочку напротив титулов, которые юзер уже перерос
        if db_user.lifetime_rating >= title.min_rating:
            marker = "✅"
        else:
            marker = "🔒"
            # Запоминаем первый заблокированный титул, как следующую цель
            if next_title is None:
                next_title = title

        lines.append(f"{marker} **{title.name}** — от {title.min_rating} {settings.CURRENCY_NAME}")

    lines.append(f"\n👤 Твой несгораемый рейтинг: **{db_user.lifetime_rating} {settings.CURRENCY_NAME}**")
    lines.append(f"🏆 Твой текущий статус: **{current_title_name}**")

    if next_title:
        points_needed = next_title.min_rating - db_user.lifetime_rating
        lines.append(f"🚀 До титула **{next_title.name}** осталось набрать: **{points_needed}** очков активности.")
    else:
        lines.append("👑 Поздравляем! Ты достиг максимального титула в системе!")

    await message.answer("\n".join(lines), parse_mode="Markdown")
