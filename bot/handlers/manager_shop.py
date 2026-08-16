from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.models import ShopItem
from bot.keyboards.manager_shop_kb import (
    get_manager_shop_keyboard, 
    get_item_admin_keyboard, 
    get_cancel_keyboard,
    get_item_type_choice_keyboard
)
from bot.states import ManagerShop

router = Router(name="manager_shop_router")

async def refresh_admin_shop(callback_or_message, session: AsyncSession):
    """Обновляет экран управления ассортиментом магазина."""
    query = select(ShopItem).where(ShopItem.is_deleted == False).order_by(ShopItem.id)
    items = (await session.execute(query)).scalars().all()

    text = (
        "📦 **Панель управления магазином товаров**\n\n"
        "Здесь вы можете добавлять новые позиции мерча, создавать лотерейные билеты "
        "для розыгрышей или удалять неактуальные товары.\n\n"
        "📋 **Текущий ассортимент витрины:**"
    )
    
    reply_markup = get_manager_shop_keyboard(items)

    if isinstance(callback_or_message, CallbackQuery):
        try: await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception: await callback_or_message.answer()
    else:
        await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")


@router.callback_query(F.data == "mg_shop_back")
async def process_mg_shop_back(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await refresh_admin_shop(callback, db_session)
    await callback.answer()


@router.callback_query(F.data.startswith("mg_shop_view:"))
async def process_mg_shop_view(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    item_id = int(callback.data.split(":")[1])

    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await callback.answer("❌ Товар не найден.", show_alert=True)
        await refresh_admin_shop(callback, db_session)
        return

    type_str = "🎟️ Лотерейный билет" if item.is_ticket else "🎒 Обычный мерч"
    text = (
        f"📦 **Карточка товара (ID: {item.id})**\n\n"
        f"▪️ **Название:** {item.name}\n"
        f"▪️ **Тип предмета:** {type_str}\n"
        f"▪️ **Цена:** {item.price} {settings.CURRENCY_NAME}\n"
        f"▪️ **Описание:** _{item.description or 'Нет описания'}_\n"
        f"▪️ **Медиа-файл:** {'✅ Прикреплен' if item.image_url else '❌ Отсутствует'}"
    )

    reply_markup = get_item_admin_keyboard(item.id)

    if item.image_url:
        # Если у товара есть фото — отправляем карточку с картинкой
        await callback.message.answer_photo(photo=item.image_url, caption=text, reply_markup=reply_markup, parse_mode="Markdown")
        try: await callback.message.delete()
        except Exception: pass
    else:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("mg_shop_del:"))
async def process_mg_shop_del(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    item_id = int(callback.data.split(":")[1])

    item = await db_session.get(ShopItem, item_id)
    if item:
        # Мягкое удаление (is_deleted = True), чтобы не поломать историю старых заказов в БД
        item.is_deleted = True
        await db_session.commit()
        await callback.answer("✅ Товар успешно удален с витрины магазина!", show_alert=True)
        
    await refresh_admin_shop(callback, db_session)

# --- FSM СЦЕНАРИЙ: ПОШАГОВОЕ СОЗДАНИЕ ТОВАРА ---

@router.callback_query(F.data == "mg_shop_add")
async def process_mg_shop_add_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerShop.waiting_for_name)
    await callback.message.answer("📝 **Добавление товара [Шаг 1/5]**\n\nВведите название нового предмета:", reply_markup=get_cancel_keyboard())
    await callback.answer()

@router.message(ManagerShop.waiting_for_name)
async def process_add_name(message: Message, state: FSMContext):
    await state.update_data(item_name=message.text.strip())
    await state.set_state(ManagerShop.waiting_for_description)
    await message.answer("📝 **Добавление товара [Шаг 2/5]**\n\nВведите подробное описание предмета:", reply_markup=get_cancel_keyboard())

@router.message(ManagerShop.waiting_for_description)
async def process_add_description(message: Message, state: FSMContext):
    await state.update_data(item_desc=message.text.strip())
    await state.set_state(ManagerShop.waiting_for_price)
    await message.answer(f"💰 **Добавление товара [Шаг 3/5]**\n\nУкажите стоимость предмета в валюте {settings.CURRENCY_NAME} (целое число):", reply_markup=get_cancel_keyboard())

@router.message(ManagerShop.waiting_for_price)
async def process_add_price(message: Message, state: FSMContext):
    if not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        await message.answer("❌ Ошибка! Цена должна быть целым положительным числом. Попробуйте еще раз:")
        return
    await state.update_data(item_price=int(message.text.strip()))
    await state.set_state(ManagerShop.waiting_for_media)
    await message.answer(
        "🖼️ **Добавление товара [Шаг 4/5]**\n\n"
        "Прикрепите и отправьте **Фотографию** или **GIF-анимацию** для карточки товара.\n\n"
        "👉 _Если вы хотите оставить товар без изображения, просто введите текст_ `пропустить`:",
        reply_markup=get_cancel_keyboard()
    )

@router.message(ManagerShop.waiting_for_media)
async def process_add_media(message: Message, state: FSMContext):
    media_url = None
    
    # Если менеджер отправил картинку
    if message.photo:
        media_url = message.photo[-1].file_id
    # Если менеджер прикрепил GIF (анимацию)
    elif message.animation:
        media_url = message.animation.file_id
    elif message.text and message.text.strip().lower() == "пропустить":
        media_url = None
    else:
        await message.answer("❌ Ошибка! Пожалуйста, отправьте корректное изображение, GIF-файл или напишите `пропустить`:")
        return

    await state.update_data(item_media=media_url)
    await state.set_state(ManagerShop.waiting_for_type)
    await message.answer("🎟️ **Добавление товара [Шаг 5/5]**\n\nВыберите категорию создаваемого предмета:", reply_markup=get_item_type_choice_keyboard())

@router.callback_query(ManagerShop.waiting_for_type, F.data.startswith("mg_type:"))
async def process_add_type_and_finalize(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    chosen_type = callback.data.split(":")[1]
    is_ticket_flag = (chosen_type == "ticket")

    data = await state.get_data()
    
    # Сохраняем готовую запись в PostgreSQL
    new_item = ShopItem(
        name=data.get("item_name"),
        description=data.get("item_desc"),
        price=data.get("item_price"),
        image_url=data.get("item_media"),
        is_ticket=is_ticket_flag
    )
    db_session.add(new_item)
    await db_session.commit()
    await state.clear()

    await callback.answer("🎉 Новый товар успешно создан и опубликован!", show_alert=True)
    await refresh_admin_shop(callback, db_session)

@router.callback_query(F.data == "mg_shop_cancel")
async def process_mg_shop_cancel(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    await state.clear()
    await callback.answer("❌ Создание предмета отменено.")
    await refresh_admin_shop(callback, db_session)
