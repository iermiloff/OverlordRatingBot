from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import User, ShopItem, Order, OrderStatus, Inventory
from bot.keyboards.shop_kb import get_shop_item_keyboard, get_order_confirm_keyboard
from bot.states import OrderCheckout

router = Router(name="shop_user_router")

ITEMS_PER_PAGE = 1

async def send_shop_page(callback_or_message, session: AsyncSession, page: int = 1):
    """Отрисовка карточки товара в магазине с поддержкой Фото/GIF и маркеров билетов."""
    count_query = select(func.count(ShopItem.id)).where(ShopItem.is_deleted == False)
    total_items = (await session.execute(count_query)).scalar()

    if total_items == 0:
        text = "🛒 **Магазин товаров**\n\nВ данный момент витрина пуста. Менеджеры добавят мерч в ближайшее время! ✨"
        from bot.keyboards.menu_kb import get_back_to_menu_keyboard
        if isinstance(callback_or_message, CallbackQuery):
            await callback_or_message.message.answer(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
            try: await callback_or_message.message.delete()
            except Exception: pass
        else:
            await callback_or_message.answer(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
        return

    offset_value = (page - 1) * ITEMS_PER_PAGE
    item_query = (
        select(ShopItem)
        .where(ShopItem.is_deleted == False)
        .order_by(ShopItem.id)
        .limit(ITEMS_PER_PAGE)
        .offset(offset_value)
    )
    item = (await session.execute(item_query)).scalar_one_or_none()
    has_next = (page * ITEMS_PER_PAGE) < total_items

    ticket_label = "🎟️ [ЛОТЕРЕЙНЫЙ БИЛЕТ]" if item.is_ticket else "🎒 [МЕРЧ / ТОВАР]"
    text = (
        f"{ticket_label}\n"
        f"🛍️ **Товар:** {item.name}\n"
        f"📝 **Описание:** {item.description or 'Нет описания'}\n\n"
        f"💰 **Цена:** {settings.CURRENCY_EMOJI} {item.price} {settings.CURRENCY_NAME}\n"
        f"🧭 _Страница {page} из {total_items}_"
    )

    reply_markup = get_shop_item_keyboard(item.id, page, has_next, item.price)

    # ЛОГИКА ВЫВОДА МЕДИАФАЙЛОВ
    if isinstance(callback_or_message, CallbackQuery):
        # Если это клик по кнопке «Вперед/Назад»
        try:
            if item.image_url:
                # Если у товара есть картинка, отправляем её новым медиа-сообщением
                await callback_or_message.message.answer_photo(
                    photo=item.image_url, caption=text, reply_markup=reply_markup, parse_mode="Markdown"
                )
                await callback_or_message.message.delete()
            else:
                # Если картинки нет — перерисовываем старый текст
                await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            # Защита от ошибок изменения типов сообщений Telegram
            if item.image_url:
                await callback_or_message.message.answer_photo(photo=item.image_url, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await callback_or_message.message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
            try: await callback_or_message.message.delete()
            except Exception: pass
    else:
        # Если зашли в магазин первый раз по кнопке меню
        if item.image_url:
            await callback_or_message.answer_photo(photo=item.image_url, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")

@router.callback_query(F.data.startswith("shop_page:"))
async def process_shop_page(callback: CallbackQuery, db_session: AsyncSession):
    page = int(callback.data.split(":")[1])
    await send_shop_page(callback, db_session, page=page)
    await callback.answer()

@router.callback_query(F.data.startswith("shop_buy:"))
async def process_buy_click(callback: CallbackQuery, db_user: User, db_session: AsyncSession, state: FSMContext):
    parts = callback.data.split(":")
    item_id, page = int(parts[1]), int(parts[2])

    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await callback.answer("❌ Данный товар более недоступен.", show_alert=True)
        await send_shop_page(callback, db_session, page=1)
        return

    if db_user.current_rating < item.price:
        await callback.answer(
            f"❌ Недостаточно средств! Вам не хватает {item.price - db_user.current_rating} {settings.CURRENCY_NAME}", 
            show_alert=True
        )
        return

    # Если товар является БИЛЕТОМ — оформляем покупку мгновенно в 1 клик, минуя сбор ФИО/Адреса
    if item.is_ticket:
        db_user.current_rating -= item.price
        
        # Проверяем, есть ли уже такой билет в инвентаре
        inv_check = await db_session.execute(
            select(Inventory).where(and_(Inventory.user_id == db_user.tg_id, Inventory.item_id == item.id))
        )
        inv_item = inv_check.scalar_one_or_none()
        
        if inv_item:
            inv_item.quantity += 1
        else:
            inv_item = Inventory(user_id=db_user.tg_id, item_id=item.id, quantity=1)
            db_session.add(inv_item)
            
        await db_session.commit()
        await callback.answer(f"🎟️ Билет '{item.name}' успешно куплен и добавлен в ваш инвентарь!", show_alert=True)
        await send_shop_page(callback, db_session, page=page)
        return

    # Для обычных товаров запускаем стандартный FSM-процесс доставки
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
    data = await state.get_data()
    item_id = data.get("buy_item_id")
    
    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await message.answer("❌ Товар исчез из магазина. Оформление отменено.")
        await state.clear()
        return

    await state.update_data(delivery_text=message.text.strip())

    text = (
        f"📝 **Проверьте корректность данных заказа:**\n\n"
        f"📦 **Товар:** {item.name}\n"
        f"💰 **Списание баланса:** {item.price} {settings.CURRENCY_NAME}\n"
        f"🚚 **Данные для доставки:**\n_{message.text}_\n\n"
        f"При нажатии на кнопку подтверждения, рейтинг спишется, а заявка упадет менеджеру."
    )
    await message.answer(text, reply_markup=get_order_confirm_keyboard(item.id), parse_mode="Markdown")

@router.callback_query(F.data.startswith("order_confirm:"))
async def process_order_confirm(callback: CallbackQuery, db_user: User, db_session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    delivery_text = data.get("delivery_text")
    
    item_id = int(callback.data.split(":")[1])
    item = await db_session.get(ShopItem, item_id)
    
    if not item or item.is_deleted:
        await callback.answer("❌ Товар удален.", show_alert=True)
        await state.clear()
        return

    if db_user.current_rating < item.price:
        await callback.answer("❌ Недостаточно рейтинга!", show_alert=True)
        await state.clear()
        return

    db_user.current_rating -= item.price

    new_order = Order(
        user_id=db_user.tg_id, source="shop", item_name=item.name,
        status=OrderStatus.CREATED, delivery_data=delivery_text
    )
    db_session.add(new_order)
    await db_session.commit()
    await state.clear()

    # Оповещаем менеджеров
    for manager_id in settings.managers_list:
        try:
            await callback.bot.send_message(
                chat_id=manager_id,
                text=f"📥 **Новый заказ мерча!**\n\n👤 Покупатель: @{db_user.username or db_user.tg_id}\n📦 Товар: *{item.name}*",
                parse_mode="Markdown"
            )
        except Exception: pass

    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await callback.message.edit_text(
        "🎉 **Заказ успешно оформлен!**\nМенеджер свяжется с вами для отправки мерча.",
        reply_markup=get_back_to_menu_keyboard(to_manager=False)
    )
    await callback.answer()

@router.callback_query(F.data == "order_cancel")
async def process_order_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await callback.message.edit_text("❌ Оформление заказа отменено.", reply_markup=get_back_to_menu_keyboard(to_manager=False))
    await callback.answer()

