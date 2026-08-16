from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.models import User
from bot.keyboards.manager_antifraud_kb import get_antifraud_actions_keyboard

router = Router(name="manager_antifraud_router")

SUSPECTS_PER_PAGE = 1

async def send_antifraud_page(message_or_query, session: AsyncSession, page: int = 1):
    """Отрисовка карточек подозрительных пользователей с пагинацией."""
    # Считаем количество активных подозреваемых
    count_query = select(func.count(User.tg_id)).where(User.is_suspicious == True)
    total_suspicious = (await session.execute(count_query)).scalar()

    if total_suspicious == 0:
        text = "🔒 **Антифрод-система**\n\nПодозрительных аккаунтов не обнаружено. Все пользователи ведут себя естественно! 👍"
        if isinstance(message_or_query, Message):
            await message_or_query.answer(text, parse_mode="Markdown")
        else:
            await message_or_query.message.edit_text(text, parse_mode="Markdown")
        return

    offset_value = (page - 1) * SUSPECTS_PER_PAGE
    query = (
        select(User)
        .where(User.is_suspicious == True)
        .order_by(User.created_at.desc())
        .limit(SUSPECTS_PER_PAGE)
        .offset(offset_value)
    )
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    # Корректировка страницы на случай, если запись обработали
    if not user and page > 1:
        await send_antifraud_page(message_or_query, session, page=page-1)
        return

    has_next = (page * SUSPECTS_PER_PAGE) < total_suspicious

    username_text = f"@{user.username}" if user.username else "нет юзернейма"
    
    text = (
        f"🔒 **Антифрод-контроль (Запись {page}/{total_suspicious})**\n\n"
        f"👤 **Пользователь:** {user.full_name} ({username_text})\n"
        f"🆔 **Telegram ID:** `{user.tg_id}`\n"
        f"💳 **Текущий баланс:** {user.current_rating} рейтинга\n"
        f"📈 **Опыт за все время:** {user.lifetime_rating} рейтинга\n\n"
        f"🚨 **Обоснование системы подозрения:**\n"
        f"_{user.antifraud_reason or 'Причина не указана'}_"
    )

    reply_markup = get_antifraud_actions_keyboard(user.tg_id, page, has_next)

    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        try:
            await message_or_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await message_or_query.answer()


@router.message(F.text == "🔒 Антифрод-система")
async def cmd_manager_antifraud(message: Message, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await send_antifraud_page(message, db_session, page=1)


router.callback_query(F.data.startswith("af_page:"))
async def process_af_page(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    page = int(callback.data.split(":"))
    await send_antifraud_page(callback, db_session, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("af_act:"))
async def process_antifraud_action(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    # Парсим: ID юзера, тип действия, текущая страница
    _, user_id, action, page = callback.data.split(":")
    user_id, page = int(user_id), int(page)

    user = await db_session.get(User, user_id)
    if not user:
        await callback.answer("❌ Пользователь не найден.", show_alert=True)
        await send_antifraud_page(callback, db_session, page=1)
        return

    alert_msg = ""
    
    if action == "clear":
        # Прощаем пользователя
        user.is_suspicious = False
        user.antifraud_reason = None
        alert_msg = "✅ Подозрение снято. Пользователь оправдан."
        
    elif action == "strip":
        # Списываем баланс, но оставляем метку подозрения активной для выбора дальнейших мер
        user.current_rating = 0
        alert_msg = "💎 Текущий баланс рейтинга полностью обнулен!"
        try:
            await callback.bot.send_message(chat_id=user.tg_id, text="⚠️ Менеджер обнулил ваш доступный баланс рейтинга за нарушение правил активности.")
        except Exception: pass
        
    elif action == "ban_temp":
        # Блокировка на 7 дней + убираем из списка подозреваемых
        user.is_banned = True
        user.ban_until = datetime.utcnow() + timedelta(days=7)
        user.is_suspicious = False
        alert_msg = "⏳ Аккаунт заблокирован в боте на 7 дней."
        try:
            await callback.bot.send_message(chat_id=user.tg_id, text="⛔ Ваш аккаунт временно заблокирован менеджером на 7 дней за подозрительную активность.")
        except Exception: pass
        
    elif action == "ban_perm":
        # Перманентный бан
        user.is_banned = True
        user.ban_until = None
        user.is_suspicious = False
        alert_msg = "⛔ Аккаунт заблокирован навсегда."
        try:
            await callback.bot.send_message(chat_id=user.tg_id, text="⛔ Ваш аккаунт заблокирован менеджером навсегда за грубое нарушение правил.")
        except Exception: pass

    await db_session.commit()
    await callback.answer(alert_msg, show_alert=True)
    
    # Перерисовываем страницу анти-фрода
    await send_antifraud_page(callback, db_session, page=page)
