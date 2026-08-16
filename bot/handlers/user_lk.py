from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

# Прямые импорты из корня и модулей пакета
from config import settings
from database.models import User, ChatConfig
from services.rating import get_user_title_name
from bot.keyboards.menu_kb import get_back_to_menu_keyboard

router = Router(name="user_lk_router")

@router.callback_query(F.data == "user_stats")
async def show_user_stats_inline(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    """Экран статистики пользователя с бесшовной перерисовкой."""
    # Вычисляем позицию в топе: считаем сколько людей набрали строго больше опыта за все время
    rank_query = select(func.count(User.tg_id)).where(User.lifetime_rating > db_user.lifetime_rating)
    rank_result = await db_session.execute(rank_query)
    user_rank = rank_result.scalar() + 1

    # Динамически вычисляем имя звания по несгораемому рейтингу
    title_name = get_user_title_name(db_user.lifetime_rating)

    text = (
        f"📊 **Твоя статистика в {settings.BOT_NAME}**\n\n"
        f"👤 **Пользователь:** {callback.from_user.mention_html()}\n"
        f"🎖️ **Текущий титул:** {title_name}\n"
        f"🏆 **Глобальный рейтинг:** #{user_rank}\n\n"
        f"💳 **Доступно для покупок:** {settings.CURRENCY_EMOJI} {db_user.current_rating} {settings.CURRENCY_NAME}\n"
        f"📈 **Всего заработано:** {settings.CURRENCY_EMOJI} {db_user.lifetime_rating} {settings.CURRENCY_NAME}\n\n"
        f"ℹ️ _Покупки в магазине списывают только доступный баланс. Твой титул и место в топе останутся неизменными!_"
    )
    
    # Меняем текст старого сообщения и прикрепляем нижнюю Inline-кнопку «Назад»
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "user_referrals")
async def show_referral_program_inline(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    """Экран партнерской программы с генерацией уникальной deep-link ссылки."""
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me{bot_info.username}?start=ref_{db_user.tg_id}"

    # Делаем три агрегирующих COUNT-запроса
    all_ref_q = select(func.count(User.tg_id)).where(User.referrer_id == db_user.tg_id)
    all_ref = (await db_session.execute(all_ref_q)).scalar()

    pending_q = select(func.count(User.tg_id)).where(User.referrer_id == db_user.tg_id, User.lifetime_rating < settings.REF_TARGET_RATING)
    pending_ref = (await db_session.execute(pending_q)).scalar()

    success_q = select(func.count(User.tg_id)).where(User.referrer_id == db_user.tg_id, User.lifetime_rating >= settings.REF_TARGET_RATING)
    success_ref = (await db_session.execute(success_q)).scalar()

    total_earned = success_ref * settings.REF_REWARD_RATING

    text = (
        f"🤝 **Партнерская программа**\n\n"
        f"Приглашай друзей и зарабатывай {settings.CURRENCY_EMOJI} **{settings.REF_REWARD_RATING} {settings.CURRENCY_NAME}** "
        f"за каждого активного участника!\n\n"
        f"💵 Бонус начислится, когда твой реферал наберет **{settings.REF_TARGET_RATING}** общего опыта.\n\n"
        f"🔗 **Твоя индивидуальная инвайт-ссылка:**\n<code>{ref_link}</code>\n\n"
        f"📊 **Статистика приглашений:**\n"
        f"▪️ Всего приглашено человек: **{all_ref}**\n"
        f"▪️ В ожидании активации (холд): **{pending_ref}**\n"
        f"▪️ Успешные рефералы: **{success_ref}**\n"
        f"💰 Заработано за всё время: **{total_earned} {settings.CURRENCY_NAME}**"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "user_titles")
async def show_titles_list_inline(callback: CallbackQuery, db_user: User):
    """Экран иерархии титулов из .env с расчетом прогресса до следующего уровня."""
    titles_config = settings.parsed_titles
    if not titles_config:
        await callback.answer("📭 Список титулов временно не настроен.")
        return

    # Упорядочиваем по возрастанию рейтинга
    sorted_titles = sorted(titles_config.values(), key=lambda x: x.min_rating)
    current_title_name = get_user_title_name(db_user.lifetime_rating)

    lines = ["🎖️ **Иерархия доступных титулов в системе:**\n"]
    next_title = None

    for title in sorted_titles:
        marker = "✅" if db_user.lifetime_rating >= title.min_rating else "🔒"
        if db_user.lifetime_rating < title.min_rating and next_title is None:
            next_title = title
        lines.append(f"{marker} **{title.name}** — от {title.min_rating} {settings.CURRENCY_NAME}")

    lines.append(f"\n👤 Твой опыт за всё время: **{db_user.lifetime_rating} {settings.CURRENCY_NAME}**")
    lines.append(f"🏆 Твой текущий статус: **{current_title_name}**")

    if next_title:
        points_needed = next_title.min_rating - db_user.lifetime_rating
        lines.append(f"🚀 До титула **{next_title.name}** осталось набрать: **{points_needed}** очков.")
    else:
        lines.append("👑 Поздравляем! Вы достигли максимального звания!")

    await callback.message.edit_text("\n".join(lines), reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "user_chats")
async def show_active_chats_list_inline(callback: CallbackQuery, db_session: AsyncSession):
    """Экран официальных чатов с поддержкой кликабельных HTML-ссылок."""
    query = select(ChatConfig).where(ChatConfig.is_active == True).order_by(ChatConfig.title)
    active_chats = (await db_session.execute(query)).scalars().all()

    if not active_chats:
        text = (
            "💬 <b>Наши Чаты</b>\n\n"
            "В данный момент нет подключенных групп для учета активности. "
            "Загляните сюда позже! ⏳"
        )
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="HTML")
        return

    lines = [
        "💬 <b>Список наших официальных чатов:</b>\n",
        f"Проявляй активность в любой из этих групп, общайся и получай автоматическую "
        f"валюту {settings.CURRENCY_EMOJI} {settings.CURRENCY_NAME} за каждое сообщение! ✨\n"
    ]

    for idx, chat in enumerate(active_chats, start=1):
        # Если бот смог выгрузить ссылку чата, оборачиваем её в HTML тег
        if chat.invite_link:
            chat_name_html = f'<a href="{chat.invite_link}">{chat.title}</a>'
        else:
            chat_name_html = f"<b>{chat.title}</b>"
            
        lines.append(f"{idx}. 👥 {chat_name_html} — <i>Учет активности активен</i>")

    await callback.message.edit_text("\n".join(lines), reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="HTML")
    await callback.answer()

