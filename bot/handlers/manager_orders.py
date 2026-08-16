from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.models import Order, OrderStatus, User
from bot.keyboards.manager_orders_kb import get_admin_order_keyboard

router = Router(name="manager_orders_router")

ORDERS_PER_PAGE = 1

async def send_admin_orders_page(message_or_query, session: AsyncSession, page: int = 1):
    """Отрисовка панели заявок для менеджера с пагинацией."""
    # Считаем только активные/новые заказы, которые требуют внимания (CREATED и PROCESSED)
    count_query = select(func.count(Order.id)).where(
        Order.status.in_([OrderStatus.CREATED, OrderStatus.PROCESSED])
    )
    total_orders = (await session.execute(count_query)).scalar()

    if total_orders == 0:
        text = "📥 **Управление заявками**\n\nНовых или обрабатываемых заявок сейчас нет. Все заказы успешно обработаны! ✨"
        if isinstance(message_or_query, Message):
            await message_or_query.answer(text, parse_mode="Markdown")
        else:
            await message_or_query.message.edit_text(text, parse_mode="Markdown")
        return

    # Запрашиваем один самый старый заказ, требующий обработки (FIFO - первый пришел, первый ушел)
    offset_value = (page - 1) * ORDERS_PER_PAGE
    order_query = (
        select(Order)
        .where(Order.status.in_([OrderStatus.CREATED, OrderStatus.PROCESSED]))
        .order_by(Order.created_at.asc())
        .limit(ORDERS_PER_PAGE)
        .offset(offset_value)
    )
    order_result = await session.execute(order_query)
    order = order_result.scalar_one_or_none()

    # Корректировка страницы, если заказ удалили/обработали прямо сейчас
    if not order and page > 1:
        await send_admin_orders_page(message_or_query, session, page=page-1)
        return

    has_next = (page * ORDERS_PER_PAGE) < total_orders

    # Получаем данные покупателя для вывода юзернейма
    buyer = await session.get(User, order.user_id)
    buyer_username = f"@{buyer.username}" if buyer and buyer.username else f"ID: {order.user_id}"

    status_labels = {
        OrderStatus.CREATED: "🆕 Новый",
        OrderStatus.PROCESSED: "⚙️ В обработке"
    }

    source_labels = {
        "shop": "🏪 Покупка в магазине",
        "chest": "📦 Выигрыш из сундука",
        "giveaway": "🎉 Выигрыш в розыгрыше"
    }

    text = (
        f"📥 **Обработка заявок (Страница {page}/{total_orders})**\n\n"
        f"🆔 **Заказ №:** `{order.id}`\n"
        f"👤 **Покупатель:** {buyer_username}\n"
        f"🎁 **Предмет:** *{order.item_name}*\n"
        f"📊 **Тип операции:** {source_labels.get(order.source, order.source)}\n"
        f"📈 **Текущий статус:** {status_labels.get(order.status)}\n"
        f"📅 **Дата:** {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"🚚 **Данные для доставки / Контакты:**\n_{order.delivery_data or 'Не указаны'}_"
    )

    reply_markup = get_admin_order_keyboard(order.id, page, has_next)

    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        try:
            await message_or_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await message_or_query.answer()


@router.message(F.text == "📥 Заявки/Заказы")
async def cmd_manager_orders(message: Message, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await send_admin_orders_page(message, db_session, page=1)


@router.types.CallbackQuery(F.data.startswith("mg_orders_page:"))
async def process_mg_orders_page(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    page = int(callback.data.split(":"))
    await send_admin_orders_page(callback, db_session, page=page)
    await callback.answer()


@router.types.CallbackQuery(F.data.startswith("mg_ord_status:"))
async def process_mg_order_status_change(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    # Парсим параметры: ID заказа, новый статус, текущая страница пагинации
    _, order_id, new_status_val, page = callback.data.split(":")
    order_id, page = int(order_id), int(page)
    new_status = OrderStatus(new_status_val)

    order = await db_session.get(Order, order_id)
    if not order:
        await callback.answer("❌ Заказ не найден.", show_alert=True)
        await send_admin_orders_page(callback, db_session, page=1)
        return

    # Обновляем статус в базе данных
    order.status = new_status
    await db_session.commit()

    # Отправляем push-уведомление пользователю
    status_notifications = {
        OrderStatus.PROCESSED: f"⚙️ Ваш заказ *'{order.item_name}'* взят менеджером в обработку.",
        OrderStatus.COMPLETED: f"🎉 Ваш заказ *'{order.item_name}'* успешно выдан / отправлен! Проверьте ЛК.",
        OrderStatus.REJECTED: f"❌ Ваш заказ *'{order.item_name}'* был отклонен менеджером. Если возникли вопросы, обратитесь в поддержку."
    }
    
    try:
        await callback.bot.send_message(
            chat_id=order.user_id,
            text=status_notifications.get(new_status),
            parse_mode="Markdown"
        )
    except Exception:
        pass # Игнорируем, если пользователь заблокировал бота

    await callback.answer(f"✅ Статус заказа №{order_id} успешно изменен!")
    
    # Обновляем страницу. Если заказ закрыт (COMPLETED/REJECTED), он исчезнет из этой выборки
    await send_admin_orders_page(callback, db_session, page=page)
