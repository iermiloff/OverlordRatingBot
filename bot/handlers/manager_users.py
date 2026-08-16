from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import settings
from database.models import User, ShopItem, Order, OrderStatus
from services.rating import get_user_title_name
from bot.keyboards.manager_users_kb import (
    get_users_list_keyboard, get_user_profile_keyboard, get_gift_items_keyboard
)
from bot.states import ManagerUserActions

router = Router(name="manager_users_router")

USERS_PER_PAGE = 5

async def send_users_page(message_or_query, session: AsyncSession, page: int = 1):
    """Отрисовка списка пользователей для менеджера."""
    count_query = select(func.count(User.tg_id))
    total_users = (await session.execute(count_query)).scalar()

    if total_users == 0:
        text = "👥 **Список пользователей**\n\nВ базе данных еще нет зарегистрированных пользователей."
        if isinstance(message_or_query, Message):
            await message_or_query.answer(text, parse_mode="Markdown")
        else:
            await message_or_query.message.edit_text(text, parse_mode="Markdown")
        return

    offset_value = (page - 1) * USERS_PER_PAGE
    users_query = select(User).order_by(User.created_at.desc()).limit(USERS_PER_PAGE).offset(offset_value)
    users = (await session.execute(users_query)).scalars().all()
    has_next = (page * USERS_PER_PAGE) < total_users

    text = f"👥 **Управление пользователями (Страница {page})**\n\nВыберите пользователя из списка ниже для просмотра досье и изменения настроек:"
    reply_markup = get_users_list_keyboard(users, page, has_next)

    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        try:
            await message_or_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await message_or_query.answer()

@router.message(F.text == "👥 Список пользователей", F.data.cast(bool) == False) # Игнорируем если флаг is_manager False, но middleware уже фильтрует
async def cmd_manager_users(message: Message, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await send_users_page(message, db_session, page=1)

@router.callback_query(F.data.startswith("mg_users_page:"))
async def process_mg_users_page(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    page = int(callback.data.split(":")[1])
    await send_users_page(callback, db_session, page=page)

@router.callback_query(F.data.startswith("mg_user_view:"))
async def process_mg_user_view(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    _, user_id, page = callback.data.split(":")
    user_id, page = int(user_id), int(page)

    user = await db_session.get(User, user_id)
    if not user:
        await callback.answer("❌ Пользователь не найден.", show_alert=True)
        return

    title_name = get_user_title_name(user.lifetime_rating)
    status_text = "❌ ЗАБАНЕН" if user.is_banned else ("⚠️ ПОДОЗРИТЕЛЬНЫЙ" if user.is_suspicious else "✅ Активен")

    text = (
        f"👤 **Досье пользователя**\n\n"
        f"▪️ **Имя:** {user.full_name}\n"
        f"▪️ **Юзернейм:** @{user.username or 'отсутствует'}\n"
        f"▪️ **Telegram ID:** `{user.tg_id}`\n"
        f"▪️ **Статус:** {status_text}\n"
        f"▪️ **Титул:** {title_name}\n\n"
        f"💳 **Текущий кошелек:** {user.current_rating} {settings.CURRENCY_NAME}\n"
        f"📈 **Опыт за все время:** {user.lifetime_rating} {settings.CURRENCY_NAME}\n"
    )
    if user.antifraud_reason:
        text += f"\n🚨 **Причина проверки анти-фродом:**\n_{user.antifraud_reason}_\n"

    await callback.message.edit_text(text, reply_markup=get_user_profile_keyboard(user.tg_id, page), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("mg_user_rate:"))
async def process_mg_user_rate_click(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    _, user_id, page = callback.data.split(":")
    
    await state.set_state(ManagerUserActions.waiting_for_rating_amount)
    await state.update_data(target_user_id=int(user_id), return_page=int(page))

    await callback.message.answer(
        "💎 **Изменение баланса пользователя**\n\n"
        "Введите целое число, на которое хотите изменить баланс.\n"
        "👉 Чтобы *начислить*, введите, например: `100`\n"
        "👉 Чтобы *снять*, введите со знаком минус: `-50`",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(ManagerUserActions.waiting_for_rating_amount)
async def process_rating_input_manager(message: Message, state: FSMContext, db_session: AsyncSession):
    data = await state.get_data()
    user_id = data.get("target_user_id")
    page = data.get("return_page")

    # Валидация ввода менеджера
    text_input = message.text.strip()
    try:
        amount = int(text_input)
    except ValueError:
        await message.answer("❌ Ошибка! Введите корректное целое число (например, 150 или -50).")
        return

    user = await db_session.get(User, user_id)
    if not user:
        await message.answer("❌ Пользователь исчез из базы данных.")
        await state.clear()
        return

    # Обновляем баланс
    user.current_rating += amount
    if amount > 0:
        user.lifetime_rating += amount # Исторический опыт растет только при начислении плюса

    await db_session.commit()
    await state.clear()

    await message.answer(f"✅ Успешно! Баланс пользователя {user.full_name} изменен на {amount} {settings.CURRENCY_NAME}.")
    
    # Автоматически отправляем пользователю уведомление о действии админа
    try:
        notification = f"🔔 Менеджер начислил вам +{amount} {settings.CURRENCY_NAME}!" if amount > 0 else f"🔔 Менеджер списал с вашего баланса {abs(amount)} {settings.CURRENCY_NAME}."
        await message.bot.send_message(chat_id=user.tg_id, text=notification)
    except Exception:
        pass

@router.callback_query(F.data.startswith("mg_user_gift:"))
async def process_mg_user_gift_click(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    _, user_id, page = callback.data.split(":")
    user_id, page = int(user_id), int(page)

    # Запрашиваем доступные товары
    items_result = await db_session.execute(select(ShopItem).where(ShopItem.is_deleted == False))
    items = items_result.scalars().all()

    if not items:
        await callback.answer("❌ В магазине нет созданных товаров для выдачи подарка.", show_alert=True)
        return

    await callback.message.edit_text(
        "🎁 **Выдача подарка от администрации**\n\nВыбери из списка товар, который будет выдан пользователю бесплатно:",
        reply_markup=get_gift_items_keyboard(items, user_id, page),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("mg_gift_confirm:"))
async def process_mg_gift_confirm(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    _, user_id, item_id, page = callback.data.split(":")
    user_id, item_id, page = int(user_id), int(item_id), int(page)

    user = await db_session.get(User, user_id)
    item = await db_session.get(ShopItem, item_id)

    if not user or not item or item.is_deleted:
        await callback.answer("❌ Ошибка: пользователь или товар не найдены.", show_alert=True)
        return

    # Оформляем заказ со статусом COMPLETED (так как админ выдает его лично на руки прямо сейчас)
    new_order = Order(
        user_id=user.tg_id,
        source="gift",
        item_name=f"[ПОДАРОК] {item.name}",
        status=OrderStatus.COMPLETED,
        delivery_data="Выдано менеджером вручную через панель управления"
    )
    db_session.add(new_order)
    await db_session.commit()

    await callback.answer(f"🎁 Товар '{item.name}' успешно подарен!", show_alert=True)
    
    # Уведомляем счастливчика
    try:
        await callback.bot.send_message(
            chat_id=user.tg_id, 
            text=f"🎉 Менеджер сделал вам подарок! Вам выдан товар: **{item.name}**.\nПроверить статус можно в '🎁 Мои Награды'."
        )
    except Exception:
        pass

    # Возвращаем менеджера в профиль юзера
    await process_mg_user_view(callback, is_manager, db_session)
