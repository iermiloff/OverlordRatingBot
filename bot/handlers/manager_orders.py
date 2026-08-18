from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

# Прямые импорты моделей и клавиатур
from database.models import Order, OrderStatus, User
from bot.keyboards.manager_orders_kb import get_admin_order_keyboard

router = Router(name="manager_orders_router")

ORDERS_PER_PAGE = 1

async def send_admin_orders_page(callback_or_message, session: AsyncSession, page: int = 1):
    """Отрисовка панели заявок для менеджера с постраничной пагинацией очереди."""
    # Считаем только те заказы, которые требуют активного внимания (CREATED и PROCESSED)
    count_query = select(func.count(Order.id)).where(
        Order.status.in_([OrderStatus.CREATED, OrderStatus.PROCESSED])
    )
    total_orders = (await session.execute(count_query)).scalar()

    if total_orders == 0:
        text = "📥 **Управление заявками**\n\nНовых или обрабатываемых заявок сейчас нет. Все заказы успешно закрыты! ✨"
        from bot.keyboards.menu_kb import get_back_to_menu_keyboard
        if isinstance(callback_or_message, CallbackQuery):
            await callback_or_message.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=True), parse_mode="Markdown")
        else:
            await callback_or_message.answer(text, reply_markup=get_back_to_menu_keyboard(to_manager=True), parse_mode="Markdown")
        return

    # Запрашиваем один самый старый заказ для обработки
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

    # Корректировка страницы, если заказ успели обработать параллельно
    if not order and page > 1:
        await send_admin_orders_page(callback_or_message, session, page=page-1)
        return

    has_next = (page * ORDERS_PER_PAGE) < total_orders

    # Извлекаем досье покупателя для вывода контактов
    buyer = await session.get(User, order.user_id)
    buyer_username = f"@{buyer.username}" if buyer and buyer.username else f"ID: {order.user_id}"

    status_labels = {
        OrderStatus.CREATED: "🆕 Новый / Ожидает",
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
        f"👤 **Покупатель:** {buyer_username} ({buyer.full_name if buyer else 'Имя скрыто'})\n"
        f"🎁 **Предмет:** *{order.item_name}*\n"
        f"📊 **Источник:** {source_labels.get(order.source, order.source)}\n"
        f"📈 **Текущий статус:** {status_labels.get(order.status)}\n"
        f"📅 **Дата создания:** {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"🚚 **Данные для доставки / Контакты:**\n_{order.delivery_data or 'Не указаны'}_"
    )

    reply_markup = get_admin_order_keyboard(order.id, page, has_next)

    if isinstance(callback_or_message, CallbackQuery):
        try:
            await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await callback_or_message.answer()
    else:
        await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")

@router.callback_query(F.data.startswith("mg_orders_page:"))
async def process_manager_orders_page_click(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Перехват клика по кнопке Заказов с безопасным разбором страницы."""
    if not is_manager: return
    
    # Извлекаем номер страницы из данных кнопки (например, из 'mg_orders_page:1')
    page = int(callback.data.split(":")[1])
    
    await render_manager_orders_page(
        callback=callback,
        page=page,
        db_session=db_session
    )

@router.callback_query(F.data.startswith("mg_ord_status:"))
async def process_mg_order_status_change(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager:
        return
    
    # ИСПРАВЛЕНО: безопасный разбор параметров по точным индексам split
    parts = callback.data.split(":")
    order_id = int(parts[1])
    new_status_val = parts[2]
    page = int(parts[3])
    
    new_status = OrderStatus(new_status_val)

    order = await db_session.get(Order, order_id)
    if not order:
        await callback.answer("❌ Заказ не найден.", show_alert=True)
        await send_admin_orders_page(callback, db_session, page=1)
        return

    # Обновляем статус в базе данных PostgreSQL
    order.status = new_status
    await db_session.commit()

    # Формируем и отправляем push-уведомление выигравшему/покупателю
    status_notifications = {
        OrderStatus.PROCESSED: f"⚙️ Ваш заказ *'{order.item_name}'* взят менеджером в обработку.",
        OrderStatus.COMPLETED: f"🎉 Ваш order *'{order.item_name}'* успешно выдан или отправлен! Проверьте в ЛК.",
        OrderStatus.REJECTED: f"❌ Ваш заказ *'{order.item_name}'* был отклонен менеджером. Обратитесь в техподдержку."
    }
    
    try:
        await callback.bot.send_message(
            chat_id=order.user_id,
            text=status_notifications.get(new_status),
            parse_mode="Markdown"
        )
    except Exception:
        pass  # Игнорируем, если пользователь заблокировал бота

    await callback.answer(f"✅ Статус заказа №{order_id} успешно изменен!")
    
    # Перерисовываем страницу. Закрытые заказы автоматически исчезнут из этой выборки
    await send_admin_orders_page(callback, db_session, page=page)

