from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import settings
from database.models import User, ShopItem, Order, OrderStatus
from bot.keyboards.shop_kb import get_shop_item_keyboard, get_order_confirm_keyboard
from bot.states import OrderCheckout

router = Router(name="shop_user_router")

ITEMS_PER_PAGE = 1

async def send_shop_page(message_or_query, session: AsyncSession, page: int = 1):
    """Универсальная функция для отрисовки страницы магазина."""
    # Считаем только активные товары (is_deleted == False)
    count_query = select(func.count(ShopItem.id)).where(ShopItem.is_deleted == False)
    total_items = (await session.execute(count_query)).scalar()

    # Защита от пустого списка (Empty State)
    if total_items == 0:
        text = "🛒 **Магазин товаров**\n\nВ данный момент витрина пуста. Менеджеры еще не добавили товары. Загляните позже!"
        if isinstance(message_or_query, Message):
            await message_or_query.answer(text, parse_mode="Markdown")
        else:
            await message_or_query.message.edit_text(text, parse_mode="Markdown")
        return

    # Извлекаем товар для текущей страницы
    offset_value = (page - 1) * ITEMS_PER_PAGE
    item_query = (
        select(ShopItem)
        .where(ShopItem.is_deleted == False)
        .order_by(ShopItem.id)
        .limit(ITEMS_PER_PAGE)
        .offset(offset_value)
    )
    item_result = await session.execute(item_query)
    item = item_result.scalar_one_or_none()

    has_next = (page * ITEMS_PER_PAGE) < total_items

    text = (
        f"🛍️ **Магазин товаров (Страница {page}/{total_items})**\n\n"
        f"📦 **Товар:** {item.name}\n"
        f"📝 **Описание:** {item.description or 'Нет описания'}\n\n"
        f"💰 **Цена:** {settings.CURRENCY_EMOJI} {item.price} {settings.CURRENCY_NAME}"
    )

    reply_markup = get_shop_item_keyboard(item.id, page, has_next, item.price)

    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        # Чтобы избежать ошибок aiogram, если текст и кнопки идентичны при повторном клике
        try:
            await message_or_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await message_or_query.answer()

@router.message(F.text == "🛍️ Магазин товаров")
async def cmd_shop(message: Message, db_session: AsyncSession):
    await send_shop_page(message, db_session, page=1)

@router.types.CallbackQuery(F.data.startswith("shop_page:"))
async def process_shop_page(callback: CallbackQuery, db_session: AsyncSession):
    page = int(callback.data.split(":")[1])
    await send_shop_page(callback, db_session, page=page)

@router.types.CallbackQuery(F.data.startswith("shop_buy:"))
async def process_buy_click(callback: CallbackQuery, db_user: User, db_session: AsyncSession, state: FSMContext):
    _, item_id, page = callback.data.split(":")
    item_id, page = int(item_id), int(page)

    # Проверяем товар в базе
    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await callback.answer("❌ Данный товар более недоступен.", show_alert=True)
        await send_shop_page(callback, db_session, page=1)
        return

    # Проверка баланса (сравниваем с текущим кошельком current_rating)
    if db_user.current_rating < item.price:
        await callback.answer(
            f"❌ Недостаточно средств! Вам не хватает {item.price - db_user.current_rating} {settings.CURRENCY_NAME}", 
            show_alert=True
        )
        return

    # Переводим пользователя в FSM-состояние заполнения данных доставки
    await state.set_state(OrderCheckout.waiting_for_delivery_data)
    await state.update_data(buy_item_id=item.id, buy_item_price=item.price)

    await callback.message.answer(
        f"🛒 **Оформление заказа: {item.name}**\n\n"
        f"Пожалуйста, введите ваши контактные данные одной строкой:\n"
        f"👉 _ФИО, город, номер телефона, адрес или способ связи с вами_.",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(OrderCheckout.waiting_for_delivery_data)
async def process_delivery_input(message: Message, state: FSMContext, db_session: AsyncSession):
    """Получаем контакты, сохраняем в FSM и просим финально подтвердить заказ."""
    data = await state.get_data()
    item_id = data.get("buy_item_id")
    
    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await message.answer("❌ Товар исчез из магазина, пока вы заполняли данные. Оформление отменено.")
        await state.clear()
        return

    # Сохраняем введенный адрес в FSM-хранилище
    await state.update_data(delivery_text=message.text)

    text = (
        f"📝 **Проверьте корректность данных заказа:**\n\n"
        f"📦 **Товар:** {item.name}\n"
        f"💰 **Списание баланса:** {item.price} {settings.CURRENCY_NAME}\n"
        f"🚚 **Данные для доставки:**\n_{message.text}_\n\n"
        f"При нажатии на кнопку подтверждения, рейтинг спишется, а заявка упадет менеджеру."
    )
    await message.answer(text, reply_markup=get_order_confirm_keyboard(item.id), parse_mode="Markdown")

@router.types.CallbackQuery(F.data.startswith("order_confirm:"))
async def process_order_confirm(callback: CallbackQuery, db_user: User, db_session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    delivery_text = data.get("delivery_text")
    
    item_id = int(callback.data.split(":")[1])
    item = await db_session.get(ShopItem, item_id)
    
    if not item or item.is_deleted:
        await callback.answer("❌ Товар удален.", show_alert=True)
        await state.clear()
        return

    # Повторная проверка баланса прямо в момент транзакции (Race Condition Protection)
    if db_user.current_rating < item.price:
        await callback.answer("❌ Недостаточно рейтинга!", show_alert=True)
        await state.clear()
        return

    # Финансовая транзакция
    db_user.current_rating -= item.price # Списываем оборотные поинты. ТИТУЛ НЕ СТРАДАЕТ!

    # Создаем запись о заказе
    new_order = Order(
        user_id=db_user.tg_id,
        source="shop",
        item_name=item.name,
        status=OrderStatus.CREATED,
        delivery_data=delivery_text
    )
    db_session.add(new_order)
    await db_session.commit()

    # Очищаем состояние
    await state.clear()

    # Оповещаем менеджеров о новом заказе
    for manager_id in settings.managers_list:
        try:
            await callback.bot.send_message(
                chat_id=manager_id,
                text=f"📥 **Новый заказ в магазине!**\n\n"
                     f"👤 Покупатель: @{db_user.username or 'без_юзернейма'} (ID: {db_user.tg_id})\n"
                     f"📦 Товар: *{item.name}*\n"
                     f"🚚 Контакты: _{delivery_text}_",
                parse_mode="Markdown"
            )
        except Exception:
            pass # Если менеджер не запустил бота лично, Telegram вернет ошибку, игнорируем ее

    await callback.message.edit_text("🎉 **Заказ успешно оформлен!**\nМенеджер свяжется с вами для отправки мерча. Проверить статус можно в кнопке '🎁 Мои Награды'.")
    await callback.answer()

@router.types.CallbackQuery(F.data == "order_cancel")
async def process_order_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Оформление заказа отменено.")
    await callback.answer()
