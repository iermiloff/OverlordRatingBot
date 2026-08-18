import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import User, ShopItem, StockUnit
from bot.states import UserPurchaseSetup # Убедись, что стейт есть в states.py

router = Router(name="user_shop_router")
logger = logging.getLogger(__name__)

# --- 🛍️ ГЛАВНАЯ ВИТРИНА МАГАЗИНА ДЛЯ ЮЗЕРОВ ---

@router.message(F.text == "🛒 Магазин Мерча / Наград")
@router.callback_query(F.data == "user_shop_main")
@router.callback_query(F.data.startswith("user_shop_page:"))
async def cmd_user_shop_main(message_or_query, db_session: AsyncSession):
    """Вывод витрины товаров с фильтрацией под Telegram и подсчетом штук."""
    page = 1
    is_callback = isinstance(message_or_query, CallbackQuery)
    
    if is_callback and message_or_query.data.startswith("user_shop_page:"):
        page = int(message_or_query.data.split(":")[1])
        
    limit = 4
    offset = (page - 1) * limit
    
    # Считаем только неудаленные товары, доступные для Telegram (all или tg)
    count_q = select(func.count(ShopItem.id)).where(
        and_(ShopItem.is_deleted == False, ShopItem.platform_target.in_(["all", "tg"]))
    )
    total = (await db_session.execute(count_q)).scalar() or 0
    
    items_q = select(ShopItem).where(
        and_(ShopItem.is_deleted == False, ShopItem.platform_target.in_(["all", "tg"]))
    ).order_by(ShopItem.price.asc()).limit(limit).offset(offset)
    items = (await db_session.execute(items_q)).scalars().all()
    
    text = (
        "🛒 **Добро пожаловать в Магазин Наград Оверлорда!**\n\n"
        "Вы можете обменять свой накопленный рейтинг активности на "
        "ценные цифровые призы, лотерейные билеты или реальный мерч.\n\n"
        f"Уникальных позиций на витрине: **{total}** шт."
    )
    
    buttons = []
    for item in items:
        # Живой подсчет единиц, выставленных администрацией на Витрину
        showcase_q = select(func.count(StockUnit.id)).where(
            and_(StockUnit.item_id == item.id, StockUnit.status == "showcase")
        )
        available_qty = (await db_session.execute(showcase_q)).scalar() or 0
        
        # Если товар закончился, пишем [НЕТ В НАЛИЧИИ]
        status_lbl = f"{item.price} {settings.CURRENCY_NAME} ({available_qty} шт)" if available_qty > 0 else "❌ НЕТ В НАЛИЧИИ"
        
        buttons.append([
            InlineKeyboardButton(
                text=f"▪️ {item.name} — {status_lbl}", 
                callback_data=f"u_item_view:{item.id}:{page}"
            )
        ])
        
    # Пагинация стрелок
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"user_shop_page:{page-1}"))
    if page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"user_shop_page:{page+1}"))
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([InlineKeyboardButton(text="↩️ Вернуться в Личный Кабинет", callback_data="user_lk_main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if is_callback:
        try: await message_or_query.message.delete()
        except Exception: pass
        await message_or_query.message.answer(text, reply_markup=kb, parse_mode="Markdown")
        await message_or_query.answer()
    else:
        await message_or_query.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- 🔎 КАРТОЧКА ТОВАРА ГЛАЗАМИ ПОЛЬЗОВАТЕЛЯ ---

@router.callback_query(F.data.startswith("u_item_view:"))
async def process_user_item_view(callback: CallbackQuery, db_session: AsyncSession):
    """Детальная карточка товара для юзера перед покупкой."""
    parts = callback.data.split(":")
    item_id = int(parts[1])
    page = int(parts[2])
    
    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await callback.answer("❌ Товар убран с витрины!", show_alert=True)
        return
        
    # Считаем доступные к покупке поштучные единицы
    showcase_q = select(func.count(StockUnit.id)).where(
        and_(StockUnit.item_id == item_id, StockUnit.status == "showcase")
    )
    qty = (await db_session.execute(showcase_q)).scalar() or 0
    
    text = (
        f"🛍️ **Товар: {item.name}**\n\n"
        f"💰 Стоимость: **{item.price}** {settings.CURRENCY_NAME}\n"
        f"📦 В наличии: **{qty}** шт.\n\n"
        f"📜 **Описание:**\n_{item.description or 'Нет описания.'}_"
    )
    
    buttons = []
    if qty > 0:
        buttons.append([
            InlineKeyboardButton(
                text="💳 КУПИТЬ СЕЙЧАС", 
                callback_data=f"u_buy_start:{item_id}:{page}"
            )
        ])
        
    buttons.append([
        InlineKeyboardButton(
            text="↩️ Вернуться на витрину", 
            callback_data=f"user_shop_page:{page}"
        )
    ])
    
    try: await callback.message.delete()
    except Exception: pass

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if item.image_url:
        await callback.message.answer_photo(
            item.image_url, caption=text, reply_markup=kb, parse_mode="Markdown"
        )
    else:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("u_buy_start:"))
async def process_user_buy_start(
    callback: CallbackQuery, db_user: User, db_session: AsyncSession
):
    """Моментальная фиксация сделки за миллисекунды без ожидания ввода адреса."""
    parts = callback.data.split(":")
    item_id = int(parts[1])
    page = int(parts[2])
    
    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await callback.answer("❌ Товар убран с витрины!", show_alert=True)
        return
        
    if db_user.current_rating < item.price:
        await callback.answer(
            f"❌ Недостаточно поинтов! Стоимость: {item.price}.", 
            show_alert=True
        )
        return
        
    # Ищем ровно одну свободную единицу на витрине
    unit_q = select(StockUnit).where(
        and_(StockUnit.item_id == item_id, StockUnit.status == "showcase")
    ).limit(1)
    unit = (await db_session.execute(unit_q)).scalar_one_or_none()
    
    if not unit:
        await callback.answer("❌ Увы! Этот товар только что раскупили!", show_alert=True)
        return
        
    # АТОМАРНОЕ ЗАКРЕПЛЕНИЕ ЗА ЮЗЕРОМ: Списание и привязка поштучного ID
    db_user.current_rating -= item.price
    unit.status = "sold"
    unit.owner_id = db_user.tg_id
    unit.purchase_source = "tg"
    
    if unit.serial_or_promo:
        # Если админ загрузил цифровой ключ — он выдается сразу
        promo_text = f"🔑 **Ваш цифровой ключ/промокод:**\n<code>{unit.serial_or_promo}</code>"
    else:
        # Физический мерч или ручной ваучер уходит в инвентарь со статусом ожидания
        unit.serial_or_promo = "[НЕ ОФОРМЛЕНО]"
        promo_text = (
            "📦 **Товар успешно закреплен в вашем инвентаре!**\n\n"
            "Вы можете оформить доставку или ввести реквизиты в любое удобное "
            "время в меню '🎒 Мой Инвентарь / Награды'."
        )
        
    await db_session.commit()
    
    try: await callback.message.delete()
    except Exception: pass
    
    await callback.message.answer(
        f"🎉 **Покупка успешно завершена!**\n\n"
        f"🎒 Вы приобрели: **{item.name}**\n"
        f"💰 Списано: {item.price} поинтов.\n\n"
        f"{promo_text}",
        parse_mode="HTML"
    )
    await callback.answer()


# --- 🏁 ФИНАЛИЗАЦИЯ И ПОДТВЕРЖДЕНИЕ ПОКУПКИ ERP ---

@router.callback_query(F.data == "u_buy_confirm_digital")
async def process_user_buy_confirm_digital(
    callback: CallbackQuery, db_user: User, db_session: AsyncSession, state: FSMContext
):
    """Мгновенное атомарное оформление цифрового товара/промокода."""
    data = await state.get_data()
    item_id = data.get("buy_item_id")
    unit_id = data.get("buy_unit_id")
    
    # Повторно извлекаем сущности внутри транзакции
    item = await db_session.get(ShopItem, item_id)
    unit = await db_session.get(StockUnit, unit_id)
    
    if not unit or unit.status != "showcase" or item.is_deleted:
        await callback.answer("❌ Ошибка! Товар уже недоступен.", show_alert=True)
        await state.clear()
        return
        
    if db_user.current_rating < item.price:
        await callback.answer("❌ Недостаточно поинтов!", show_alert=True)
        await state.clear()
        return
        
    # АТОМАРНАЯ СДЕЛКА СУБД: Списание и привязка поштучного ID
    db_user.current_rating -= item.price
    unit.status = "sold"
    unit.owner_id = db_user.tg_id
    unit.purchase_source = "tg"
    
    await db_session.commit()
    await state.clear()
    
    await callback.message.answer(
        f"🎉 **Покупка успешно завершена!**\n\n"
        f"🎒 Вы приобрели: **{item.name}**\n"
        f"💰 Списано: {item.price} поинтов.\n\n"
        f"🔑 **Ваш цифровой ключ/промокод:**\n"
        f"<code>{unit.serial_or_promo}</code>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(F.state == "UserPurchaseSetup:waiting_for_delivery")
async def process_user_buy_delivery_save(
    message: Message, db_user: User, db_session: AsyncSession, state: FSMContext
):
    """Оформление физического мерча с сохранением контактов доставки."""
    delivery_text = message.text.strip()
    data = await state.get_data()
    item_id = data.get("buy_item_id")
    unit_id = data.get("buy_unit_id")
    
    item = await db_session.get(ShopItem, item_id)
    unit = await db_session.get(StockUnit, unit_id)
    
    if not unit or unit.status != "showcase" or item.is_deleted:
        await message.answer("❌ Ошибка! Товар успели забрать или убрать с витрины.")
        await state.clear()
        return
        
    if db_user.current_rating < item.price:
        await message.answer("❌ Недостаточно поинтов на балансе!")
        await state.clear()
        return
        
    # АТОМАРНАЯ СДЕЛКА СУБД: Списание, привязка владельца и сохранение данных
    db_user.current_rating -= item.price
    unit.status = "sold"
    unit.owner_id = db_user.tg_id
    unit.purchase_source = "tg"
    
    # Записываем контакты прямо в серийное поле единицы для No-Code истории
    unit.serial_or_promo = f"[ЗАЯВКА]: {delivery_text}"
    
    await db_session.commit()
    await state.clear()
    
    await message.answer(
        f"🎉 **Заявка на товар успешно оформлена!**\n\n"
        f"🎒 Товар: **{item.name}**\n"
        f"💰 Списано: {item.price} поинтов.\n\n"
        f"Модераторы свяжутся с вами. Проверить статус "
        f"и ID предмета можно в вашем Инвентаре."
    )
    
    # Алерт менеджерам о новой заявке на мерч
    for manager_id in settings.managers_list:
        try:
            await message.bot.send_message(
                chat_id=manager_id,
                text=f"🛍️ **Новый заказ мерча [ERP Склад]**\n\n"
                     f"👤 Покупатель: @{db_user.username or db_user.tg_id}\n"
                     f"📦 Товар: *{item.name}* (Единица ID: {unit.id})\n"
                     f"📋 **Контакты:**\n_{delivery_text}_",
                parse_mode="Markdown"
            )
        except Exception: pass

@router.callback_query(F.data == "cc_cancel")
async def process_purchase_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Оформление покупки отменено.")
    await callback.answer()

