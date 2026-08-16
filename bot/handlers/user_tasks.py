from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from config import settings
from database.models import User, PromoChannel, ActivityLog, Order, OrderStatus

router = Router(name="user_tasks_router")

# --- ЛОКАЛЬНЫЕ ИНЛАЙН-КЛАВИАТУРЫ ---

def get_tasks_keyboard(channels: list, completed_ids: set) -> InlineKeyboardMarkup:
    """Генерирует инлайн-список каналов для подписки с кнопкой Назад."""
    buttons = []
    for ch in channels:
        if ch.id in completed_ids:
            buttons.append([InlineKeyboardButton(text="✅ Подписка оформлена (Получено)", callback_data="noop")])
        else:
            buttons.append([
                InlineKeyboardButton(text="📢 Перейти в канал", url=ch.invite_link),
                InlineKeyboardButton(text="💎 Проверить подписку", callback_data=f"check_sub:{ch.id}")
            ])
            
    # Инлайн-кнопка возврата в главное пользовательское меню
    buttons.append([
        InlineKeyboardButton(text="↩️ Вернуться в главное меню", callback_data="main_menu_user")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ХЭНДЛЕРЫ: ОТОБРАЖЕНИЕ СПИСКА ЗАДАНИЙ ---

@router.message(F.text == "📝 Задания")
@router.callback_query(F.data == "user_tasks") # ДОБАВЛЕНО: Теперь экранные кнопки меню оживут!
async def show_user_tasks(callback_or_message, db_user: User, db_session: AsyncSession):
    """Выводит список промоканалов с проверкой на подписку."""
    channels_result = await db_session.execute(select(PromoChannel))
    channels = channels_result.scalars().all()

    # Защита от пустого списка заданий
    if not channels:
        text = "📝 **Доступные задания**\n\nВ данный момент заданий на подписку нет. Проверьте позже!"
        from bot.keyboards.menu_kb import get_back_to_menu_keyboard
        if isinstance(callback_or_message, CallbackQuery):
            await callback_or_message.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
        else:
            await callback_or_message.answer(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
        return

    # Извлекаем задания, за которые юзер уже получил награду
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
    
    reply_markup = get_tasks_keyboard(channels, completed_ids)

    if isinstance(callback_or_message, CallbackQuery):
        try:
            await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await callback_or_message.answer()
    else:
        await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")

# --- ХЭНДЛЕРЫ: ПРОВЕРКА ПОДПИСКИ ЧЕРЕЗ API TELEGRAM ---

@router.callback_query(F.data.startswith("check_sub:"))
async def process_check_subscription(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    # ИСПРАВЛЕНО: корректно извлекаем ID канала по индексу 1 из split строк
    channel_id = int(callback.data.split(":")[1])

    # Проверяем накрутку: не получал ли юзер награду за этот канал ранее
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
        # Прямой асинхронный запрос к серверам Telegram для проверки статуса членства
        member = await callback.bot.get_chat_member(chat_id=channel_id, user_id=db_user.tg_id)
        
        # Если статус соответствует участнику, админу или владельцу
        if member.status in ["member", "administrator", "creator"]:
            # Проводим транзакцию начисления
            db_user.current_rating += channel.reward
            db_user.lifetime_rating += channel.reward

            # Фиксируем лог выполнения задания (message_length=0 как маркер задания)
            task_log = ActivityLog(user_id=db_user.tg_id, chat_id=channel_id, message_length=0)
            db_session.add(task_log)
            await db_session.commit()

            await callback.answer(f"✅ Успешно! Вам начислено +{channel.reward} {settings.CURRENCY_NAME}", show_alert=True)
            
            # Перерисовываем экран заданий на лету с учетом нового выполненного статуса
            await show_user_tasks(callback, db_user, db_session)
        else:
            await callback.answer("❌ Подписка не найдена. Сначала вступите в канал!", show_alert=True)
    except Exception:
        await callback.answer("⚠️ Ошибка проверки. Убедитесь, что бот добавлен администратором в целевой канал.", show_alert=True)

# --- ХЭНДЛЕРЫ: ИСТОРИЯ НАГРАД ПОЛЬЗОВАТЕЛЯ ---

REWARDS_PER_PAGE = 3

def get_rewards_pagination_keyboard(page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Внутренний генератор пагинации для наград с кнопкой Назад."""
    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rewards_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"rewards_page:{page+1}"))
    
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="↩️ Вернуться в главное меню", callback_data="main_menu_user")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def send_rewards_page(callback_or_message, session: AsyncSession, user_id: int, page: int = 1):
    """Отрисовка списка истории наград пользователя."""
    count_query = select(func.count(Order.id)).where(Order.user_id == user_id)
    total_orders = (await session.execute(count_query)).scalar()

    if total_orders == 0:
        text = "🎁 **Мои Награды**\n\nВы еще не совершали покупок в магазине и не выигрывали в активностях чата. Время это исправить! 🚀"
        from bot.keyboards.menu_kb import get_back_to_menu_keyboard
        if isinstance(callback_or_message, CallbackQuery):
            await callback_or_message.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
        else:
            await callback_or_message.answer(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
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

    if isinstance(callback_or_message, CallbackQuery):
        try:
            await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await callback_or_message.answer()
    else:
        await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")

@router.message(F.text == "🎁 Мои Награды")
async def cmd_my_rewards(message: Message, db_user: User, db_session: AsyncSession):
    await send_rewards_page(message, db_session, db_user.tg_id, page=1)

@router.callback_query(F.data.startswith("rewards_page:"))
async def process_rewards_page(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    # ИСПРАВЛЕНО: корректно извлекаем номер страницы по индексу 1 из split строк
    page = int(callback.data.split(":")[1])
    await send_rewards_page(callback, db_session, db_user.tg_id, page=page)
    await callback.answer()

@router.callback_query(F.data == "noop")
async def process_noop(callback: CallbackQuery):
    await callback.answer()

