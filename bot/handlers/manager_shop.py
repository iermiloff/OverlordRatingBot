from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.models import ShopItem
from bot.keyboards.manager_shop_kb import (
    get_manager_shop_keyboard, get_item_admin_keyboard, get_cancel_keyboard
)
from bot.states import ManagerShopCreate

router = Router(name="manager_shop_router")

async def refresh_manager_shop(message_or_query, session: AsyncSession):
    """Обновляет и выводит текущую панель товаров для менеджера."""
    # Извлекаем товары, исключая удаленные
    result = await session.execute(select(ShopItem).where(ShopItem.is_deleted == False).order_by(ShopItem.id.desc()))
    items = result.scalars().all()

    text = (
        "📦 **Панель управления магазином**\n\n"
        "Здесь вы можете добавлять новые товары, которые пользователи будут покупать за рейтинг, "
        "или удалять старые позиции из витрины.\n\n"
        "👇 Текущий ассортимент:"
    )
    if not items:
        text += "\n_(в магазине пока нет активных товаров)_"

    reply_markup = get_manager_shop_keyboard(items)

    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        try:
            await message_or_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await message_or_query.answer()

@router.message(F.text == "📦 Настройка магазина")
async def cmd_manager_shop(message: Message, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await refresh_manager_shop(message, db_session)

@router.callback_query(F.data == "mg_shop_back")
async def process_mg_shop_back(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await refresh_manager_shop(callback, db_session)
    await callback.answer()

@router.callback_query(F.data.startswith("mg_shop_view:"))
async def process_mg_shop_view(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    item_id = int(callback.data.split(":")[1])

    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await callback.answer("❌ Товар не найден или уже удален.", show_alert=True)
        await refresh_manager_shop(callback, db_session)
        return

    text = (
        f"📦 **Карточка товара в админке**\n\n"
        f"▪️ **Название:** {item.name}\n"
        f"▪️ **Описание:** {item.description or 'Отсутствует'}\n"
        f"▪️ **Цена:** {item.price} {settings.CURRENCY_NAME}\n\n"
        f"⚠️ _При удалении товар пропадет с витрины пользователей, но останется в базе данных "
        f"для сохранения истории прошлых покупок._"
    )
    await callback.message.edit_text(text, reply_markup=get_item_admin_keyboard(item.id), parse_mode="Markdown")
    await callback.answer()
    
@router.callback_query(F.data.startswith("mg_shop_del:"))
async def process_mg_shop_del(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    item_id = int(callback.data.split(":")[1])

    item = await db_session.get(ShopItem, item_id)
    if item:
        item.is_deleted = True # Мягкое удаление
        await db_session.commit()
        await callback.answer("✅ Товар успешно убран из магазина!", show_alert=True)
    
    await refresh_manager_shop(callback, db_session)

# --- ПОШАГОВЫЙ СЦЕНАРИЙ ДОБАВЛЕНИЯ ТОВАРА (FSM) ---

@router.callback_query(F.data == "mg_shop_add")
async def process_mg_shop_add_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerShopCreate.waiting_for_name)
    
    await callback.message.answer(
        "➕ **Добавление нового товара [Шаг 1/3]**\n\nВведите **название** товара (например: _Фирменная футболка Crypto_):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(ManagerShopCreate.waiting_for_name)
async def process_item_name(message: Message, state: FSMContext):
    await state.update_data(item_name=message.text.strip())
    await state.set_state(ManagerShopCreate.waiting_for_description)
    
    await message.answer(
        "📝 **Добавление нового товара [Шаг 2/3]**\n\nВведите **описание** товара (характеристики, размеры, условия выдачи):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )

@router.message(ManagerShopCreate.waiting_for_description)
async def process_item_description(message: Message, state: FSMContext):
    await state.update_data(item_desc=message.text.strip())
    await state.set_state(ManagerShopCreate.waiting_for_price)
    
    await message.answer(
        f"💰 **Добавление нового товара [Шаг 3/3]**\n\nУкажите **цену** товара в нашей валюте ({settings.CURRENCY_NAME}). Введите целое положительное число:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )

@router.message(ManagerShopCreate.waiting_for_price)
async def process_item_price(message: Message, state: FSMContext, db_session: AsyncSession):
    # Валидация ценника
    raw_price = message.text.strip()
    if not raw_price.isdigit() or int(raw_price) <= 0:
        await message.answer("❌ Ошибка! Цена должна быть целым положительным числом. Попробуйте еще раз:")
        return

    data = await state.get_data()
    
    # Сохраняем в PostgreSQL через SQLAlchemy
    new_item = ShopItem(
        name=data.get("item_name"),
        description=data.get("item_desc"),
        price=int(raw_price)
    )
    db_session.add(new_item)
    await db_session.commit()
    await state.clear()

    await message.answer(f"🎉 Товар **{new_item.name}** успешно добавлен и выставлен на витрину магазина!")
    await refresh_manager_shop(message, db_session)

@router.callback_query(F.data == "mg_shop_cancel")
async def process_mg_shop_cancel(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    await state.clear()
    await callback.message.edit_text("❌ Создание товара отменено.")
    await refresh_manager_shop(callback, db_session)
    await callback.answer()

def get_item_type_choice_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора: является ли создаваемый товар лотерейным билетом."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎒 Обычный мерч / товар", callback_data="mg_type:merch"),
            InlineKeyboardButton(text="🎟️ Лотерейный билет", callback_data="mg_type:ticket")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="mg_shop_cancel")]
    ])
