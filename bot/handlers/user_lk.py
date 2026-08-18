from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import User, ChatConfig, ActivityLog
from bot.keyboards.menu_kb import get_back_to_menu_keyboard, get_user_inline_menu

router = Router(name="user_lk_router")

@router.callback_query(F.data == "user_lk_main")
async def cmd_user_lk_main_hub(
    callback: CallbackQuery, db_user: User, db_session: AsyncSession
):
    """Центральный узел ЛК. Отрисовывает сетку кнопок для пользователя."""
    text = (
        f"👤 **Личный Кабинет Участника**\n\n"
        f"▪️ Покровитель: {callback.from_user.mention_html()}\n"
        f"💰 Баланс: **{db_user.current_rating}** {settings.CURRENCY_NAME}\n"
        f"🏆 Общий опыт: **{db_user.lifetime_rating}** XP"
    )

    from bot.keyboards.menu_kb import get_user_inline_menu
    
    try:
        await callback.message.edit_text(
            text=text, 
            reply_markup=get_user_inline_menu(), 
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "user_chats")
async def show_user_chats(callback: CallbackQuery, db_session: AsyncSession):
    """Выводит список всех подключенных групп проекта с инлайн-ссылками."""
    query = select(ChatConfig).where(ChatConfig.is_active == True).order_by(ChatConfig.title)
    chats = (await db_session.execute(query)).scalars().all()

    if not chats:
        text = "💬 **Наши Чаты**\n\nВ данный момент нет подключенных активных чатов. Пожалуйста, обратитесь к администрации! ✨"
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
        await callback.answer()
        return

    lines = ["💬 **Наши официальные чаты активности:**\n", "Общайтесь в этих группах, чтобы зарабатывать рейтинг и повышать свой ранг:\n"]
    for idx, chat in enumerate(chats, start=1):
        if chat.invite_link:
            lines.append(f"{idx}. 🔗 [{chat.title}]({chat.invite_link})")
        else:
            lines.append(f"{idx}. 💬 **{chat.title}** (ссылка не задана)")

    text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown", disable_web_page_preview=True)
    await callback.answer()

# --- РАЗДЕЛ ПАРТНЕРСКОЙ ПРОГРАММЫ ---

@router.callback_query(F.data == "user_referrals")
async def show_user_referrals(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    """Выводит данные реферальной системы пользователя."""
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={db_user.tg_id}"

    count_q = select(func.count(User.tg_id)).where(User.referrer_id == db_user.tg_id)
    total_refs = (await db_session.execute(count_q)).scalar() or 0

    text = (
        "🤝 **Партнерская программа проекта**\n\n"
        f"Приглашайте друзей и получайте бонус в размере **{settings.REF_REWARD_RATING}** {settings.CURRENCY_NAME} "
        "за каждого реферала, проявившего активность в чатах!\n\n"
        f"👥 Всего приглашено партнеров: **{total_refs}** чел.\n\n"
        f"🔗 Ваша уникальная реферальная ссылка:\n`{ref_link}`"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
    await callback.answer()

# --- РАЗДЕЛ ЛИЧНОЙ СТАТИСТИКИ (АДАПТИВНАЯ ГЕЙМИФИКАЦИЯ) ---

@router.callback_query(F.data == "user_stats")
async def show_user_stats(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    """Выводит личную карточку статистики пользователя в ЛК с учетом штрафов за траты."""
    msg_count_q = select(func.count(ActivityLog.id)).where(
        and_(
            ActivityLog.user_id == db_user.tg_id,
            ActivityLog.message_length > 0
        )
    )
    total_messages = (await db_session.execute(msg_count_q)).scalar() or 0

    titles = settings.parsed_titles
    sorted_titles = sorted(titles.values(), key=lambda x: x.min_rating)

    current_title_name = "Новичок"
    current_title_id = 1
    current_title_min = 0
    for t in sorted_titles:
        if db_user.lifetime_rating >= t.min_rating:
            current_title_name = t.name
            current_title_id = t.id
            current_title_min = t.min_rating

    next_title_name = "Максимум"
    next_title_required = 0
    has_next = False

    for t in sorted_titles:
        if t.id > current_title_id:
            next_title_name = t.name
            next_title_required = t.min_rating
            has_next = True
            break

    if has_next:
        if db_user.current_rating >= next_title_required:
            progress_bar = "██████████ 100%"
            remains_text = f"✨ Доступно получение титула <b>'{next_title_name}'</b> при следующем начислении опыта!"
        else:
            needed = next_title_required - db_user.current_rating
            
            range_total = next_title_required - current_title_min
            current_progress = db_user.current_rating - current_title_min
            if current_progress < 0: 
                current_progress = 0
                
            percent = int((current_progress / range_total) * 100) if range_total > 0 else 0
            percent = min(max(percent, 0), 99)
            
            filled_blocks = int(percent // 10)
            progress_bar = f"{'█' * filled_blocks}{'░' * (10 - filled_blocks)} {percent}%"
            remains_text = f"🎯 До титула <b>'{next_title_name}'</b> осталось накопить: <b>{needed}</b> {settings.CURRENCY_NAME}"
    else:
        progress_bar = "██████████ 100%"
        remains_text = "👑 Вы достигли вершины карьерной лестницы чата!"

    text = (
        f"📊 <b>Ваша личная игровая статистика:</b>\n\n"
        f"👤 ID аккаунта: <code>{db_user.tg_id}</code>\n"
        f"🎖️ Текущий Ранг: <b>{current_title_name}</b> <i>(несгораемый)</i>\n\n"
        f"💰 Доступный баланс: <b>{db_user.current_rating}</b> {settings.CURRENCY_NAME}\n"
        f"💎 Исторический опыт: <b>{db_user.lifetime_rating}</b> XP\n"
        f"💬 Отправлено сообщений: <b>{total_messages}</b> шт.\n\n"
        f"🧭 <u>Прогресс до следующего звания (от кошелька):</u>\n"
        f"<code>{progress_bar}</code>\n"
        f"{remains_text}"
    )

    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="HTML")
    await callback.answer()

# --- СТАТИЧЕСКИЙ СПИСОК ТИТУЛОВ ДЛЯ СПРАВКИ ---

@router.callback_query(F.data == "user_titles")
async def show_user_titles_list(callback: CallbackQuery):
    """Выводит справочную информацию по всей иерархии званий проекта."""
    titles = settings.parsed_titles
    
    lines = [
        "🎖️ **Иерархия рангов и званий нашей экосистемы:**\n",
        "Общайтесь в чатах, чтобы копить опыт. Текущий титул не сгорает при тратах, "
        "но покупка мерча и билетов отдаляет вас от следующего левела! 💸\n"
    ]

    # ИСПРАВЛЕНО: Сортируем кортежи .items() по полю min_rating через индекс [1] объекта
    for t_id, t in sorted(titles.items(), key=lambda x: x[1].min_rating):
        lines.append(f"▪️ Титул **\"{t.name}\"** — от `{t.min_rating}` XP")

    text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
    await callback.answer()

