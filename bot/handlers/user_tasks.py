from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import User, PromoChannel, Order, OrderStatus, ActivityLog

router = Router(name="user_tasks_router")

# --- ЛОКАЛЬНЫЕ КЛАВИАТУРЫ МОДУЛЯ ---

def get_tasks_keyboard(channels: list, completed_ids: set) -> InlineKeyboardMarkup:
    """Генерирует список каналов для подписки."""
    buttons = []
    for ch in channels:
        if ch.id in completed_ids:
            buttons.append([InlineKeyboardButton(text="✅ Подписка оформлена (Получено)", callback_data="noop")])
        else:
            buttons.append([
                InlineKeyboardButton(text="📢 Перейти в канал", url=ch.invite_link),
                InlineKeyboardButton(text="💎 Проверить", callback_data=f"check_sub:{ch.id}")
            ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_rewards_pagination_keyboard(page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Пагинация для истории наград и заказов."""
    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rewards_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"rewards_page:{page+1}"))
    
    if nav_row:
        buttons.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ХЭНДЛЕРЫ: РАЗДЕЛ ЗАДАНИЙ ---

@router.message(F.text == "📝 Задания")
async def show_user_tasks(message: Message, db_user: User, db_session: AsyncSession):
    """Выводит список промоканалов с проверкой на подписку."""
    channels_result = await db_session.execute(select(PromoChannel))
    channels = channels_result.scalars().all()

    if not channels:
        await message.answer("📝 **Доступные задания**\n\nВ данный момент заданий на подписку нет. Проверьте позже!")
        return

    completed_result = await db_session.execute(
        select(ActivityLog.chat_id).where(
            and_(ActivityLog.user_id == db_user.tg_id, ActivityLog.message_length == 0)
        )
    )
    completed_ids = set(completed_result.scalars().all())

    text = (
        f"📝 **Задания на подписку**\n\n"
        f"Подписывайся на каналы наших партнеров и получай мгновенный бонус к рейтингу! "
        f"Бот начисляет {settings.CURRENCY_EMOJI} {settings.CURRENCY_NAME} сразу после проверки."
    )
    await message.answer(text, reply_markup=get_tasks_keyboard(channels, completed_ids), parse_mode="Markdown")

@router.callback_query(F.data.startswith("check_sub:"))
async def process_check_subscription(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    channel_id = int(callback.data.split(":")[1])

    dup_check = await db_session.execute(
        select(ActivityLog).where(
            and_(ActivityLog.user_id == db_user.tg_id, ActivityLog.chat_id == channel_id, ActivityLog.message_length == 0)
        )
    )
    if dup_check.scalar_one_or_none():
        await callback.answer("❌ Вы уже получили награду за это задание!", show_alert=True)
        return

    channel = await db_session.get(PromoChannel, channel_id)
    if not channel:
        await callback.answer("❌ Задание больше не актуально.", show_alert=True)
        return

    try:
        member = await callback.bot.get_chat_member(chat_id=channel_id, user_id=db_user.tg_id)
        if member.status in ["member", "administrator", "creator"]:
            db_user.current_rating += channel.reward
            db_user.lifetime_rating += channel.reward

            task_log = ActivityLog(user_id=db_user.tg_id, chat_id=channel_id, message_length=0)
            db_session.add(task_log)
            await db_session.commit()

            await callback.answer(f"✅ Успешно! Вам начислено +{channel.reward} {settings.CURRENCY_NAME}", show_alert=True)
            await show_user_tasks(callback.message, db_user, db_session)
            try: await callback.message.delete()
            except Exception: pass
        else:
            await callback.answer("❌ Подписка не найдена. Сначала вступите в канал!", show_alert=True)
    except Exception:
        await callback.answer("⚠️ Ошибка проверки. Убедитесь, что бот добавлен администратором в целевой канал.", show_alert=True)

# --- ХЭНДЛЕРЫ: ИСТОРИЯ НАГРАД ---

REWARDS_PER_PAGE = 3

async def send_rewards_page(message_or_query, session: AsyncSession, user_id: int, page: int = 1):
    """Отрисовка списка истории наград пользователя."""
    count_query = select(func.count(Order.id)).where(Order.user_id == user_id)
    total_orders = (await session.execute(count_query)).scalar()

    if total_orders == 0:
        text = "🎁 **Мои Награды**\n\nВы еще не совершали покупок в магазине и не выигрывали в активностях чата. Время это исправить! 🚀"
        if isinstance(message_or_query, Message):
            await message_or_query.answer(text, parse_mode="Markdown")
        else:
            await message_or_query.message.edit_text(text, parse_mode="Markdown")
        return

    offset_value = (page - 1) * REWARDS_PER_PAGE
    orders_query = (
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(REWARDS_PER_PAGE)
        .offset(offset_value)
    )
    orders = (await session.execute(orders_query)).scalars().all()
    has_next = (page * REWARDS_PER_PAGE) < total_orders

    status_mapping = {
        OrderStatus.CREATED: "⏳ Создан / Ожидает обработки",
        OrderStatus.PROCESSED: "⚙️ В обработке у менеджера",
        OrderStatus.COMPLETED: "✅ Успешно доставлен / Выдан",
        OrderStatus.REJECTED: "❌ Отклонен менеджером"
    }

    lines = [f"🎁 **Твои награды и заказы (Страница {page})**\n"]
    for idx, order in enumerate(orders, start=offset_value + 1):
        source_text = "🏪 Магазин" if order.source == "shop" else "📦 Секретный сундук"
        date_str = order.created_at.strftime("%d.%m.%Y %H:%M")
        
        lines.append(
            f"{idx}. *{order.item_name}*\n"
            f"   ▪️ Источник: {source_text}\n"
            f"   ▪️ Дата: {date_str}\n"
            f"   ▪️ Статус: {status_mapping.get(order.status)}\n"
        )

    text = "\n".join(lines)
    reply_markup = get_rewards_pagination_keyboard(page, has_next)

    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        try: await message_or_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception: await message_or_query.answer()

@router.message(F.text == "🎁 Мои Награды")
async def cmd_my_rewards(message: Message, db_user: User, db_session: AsyncSession):
    await send_rewards_page(message, db_session, db_user.tg_id, page=1)

@router.callback_query(F.data.startswith("rewards_page:"))
async def process_rewards_page(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    page = int(callback.data.split(":")[1])
    await send_rewards_page(callback, db_session, db_user.tg_id, page=page)

@router.callback_query(F.data == "noop")
async def process_noop(callback: CallbackQuery):
    await callback.answer()
