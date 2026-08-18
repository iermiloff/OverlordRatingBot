import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import ShopItem, StockUnit
from bot.states import ManagerShopItemSetup # Убедись, что класс обновлен в states.py

router = Router(name="manager_shop_inventory_router")
logger = logging.getLogger(__name__)

# --- 📦 ГЛАВНОЕ МЕНЮ: СКЛАД ВИТРИНА ---

@router.callback_query(F.data == "mg_shop_back")
@router.callback_query(F.data.startswith("mg_stock_page:"))
async def cmd_manager_shop_stock_main(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Вывод списка товаров с живым подсчетом поштучных остатков ERP."""
    if not is_manager: return
    
    page = 1
    if callback.data.startswith("mg_stock_page:"):
        page = int(callback.data.split(":")[1])
        
    limit = 4
    offset = (page - 1) * limit
    
    # Считаем карточки товаров
    count_q = select(func.count(ShopItem.id)).where(ShopItem.is_deleted == False)
    total = (await db_session.execute(count_q)).scalar() or 0
    
    items_q = select(ShopItem).where(
        ShopItem.is_deleted == False
    ).order_by(ShopItem.created_at.desc()).limit(limit).offset(offset)
    items = (await db_session.execute(items_q)).scalars().all()
    
    text = (
        "🛍️ **No-Code Управление Складом и Витриной**\n\n"
        "Каждая единица товара учитывается поштучно по уникальному ID. "
        "Товары со склада скрыты от юзеров и могут быть придержаны для розыгрышей. "
        "Перенос на витрину открывает публичные продажи.\n\n"
        f"Всего позиций в базе: **{total}** шт."
    )
    
    buttons = []
    for item in items:
        # Атомарно считаем, сколько единиц лежит на Складе, а сколько на Витрине
        st_q = select(func.count(StockUnit.id)).where(
            and_(StockUnit.item_id == item.id, StockUnit.status == "stock")
        )
        sh_q = select(func.count(StockUnit.id)).where(
            and_(StockUnit.item_id == item.id, StockUnit.status == "showcase")
        )
        
        in_stock = (await db_session.execute(st_q)).scalar() or 0
        on_showcase = (await db_session.execute(sh_q)).scalar() or 0
        
        buttons.append([
            InlineKeyboardButton(
                text=f"📦 {item.name} (Склад: {in_stock} | Витрина: {on_showcase})", 
                callback_data=f"mg_item_card:{item.id}:{page}"
            )
        ])
        
    # Пагинация стрелок
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_stock_page:{page-1}"))
    if page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"mg_stock_page:{page+1}"))
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([InlineKeyboardButton(text="➕ Создать новую карточку товара", callback_data="mg_item_create_start")])
    buttons.append([InlineKeyboardButton(text="↩️ Вернуться в корень админки", callback_data="main_menu_manager")])
    
    try: await callback.message.delete()
    except Exception: pass
    
    await callback.message.answer(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown"
    )
    await callback.answer()

# --- 📦 ДЕТАЛЬНАЯ КАРТОЧКА УПРАВЛЕНИЯ ТОВАРОМ ---

@router.callback_query(F.data.startswith("mg_item_card:"))
async def process_mg_item_card_view(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Детальное управление товаром: остатки склада, витрины и лимиты."""
    if not is_manager: return
    parts = callback.data.split(":")
    item_id = int(parts[1])
    page = int(parts[2])
    
    item = await db_session.get(ShopItem, item_id)
    if not item or item.is_deleted:
        await callback.answer("❌ Товар не найден!", show_alert=True)
        return
        
    # Считаем остатки по статусам
    stock_cnt = (await db_session.execute(select(func.count(StockUnit.id)).where(
        and_(StockUnit.item_id == item_id, StockUnit.status == "stock")
    ))).scalar() or 0
    showcase_cnt = (await db_session.execute(select(func.count(StockUnit.id)).where(
        and_(StockUnit.item_id == item_id, StockUnit.status == "showcase")
    ))).scalar() or 0
    sold_cnt = (await db_session.execute(select(func.count(StockUnit.id)).where(
        and_(StockUnit.item_id == item_id, StockUnit.status == "sold")
    ))).scalar() or 0

    p_lbl = "Все" if item.platform_target == "all" else item.platform_target.upper()
    text = (
        f"🛍️ **Товар: {item.name}**\n\n"
        f"💰 Цена: **{item.price}** {settings.CURRENCY_NAME}\n"
        f"🌐 Платформа: `{p_lbl}`\n"
        f"🎟️ Тип: {'Лотерейный билет' if item.is_ticket else 'Обычный товар'}\n\n"
        f"📊 **Состояние запасов ERP:**\n"
        f"▪️ В резерве склада: **{stock_cnt}** шт. _(скрыты)_\n"
        f"▪️ На публичной витрине: **{showcase_cnt}** шт. _(в продаже)_\n"
        f"▪️ Всего продано/выдано: **{sold_cnt}** шт.\n\n"
        f"📜 **Описание карточки:**\n_{item.description or 'Нет описания'}_"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Загрузить на Склад", 
                                 callback_data=f"mg_stock_load:{item_id}:{page}"),
            InlineKeyboardButton(text="🛍️ Выставить на Витрину", 
                                 callback_data=f"mg_showcase_push:{item_id}:{page}")
        ],
        [
            InlineKeyboardButton(text="🗑️ Удалить карточку", 
                                 callback_data=f"mg_item_del:{item_id}:{page}"),
            InlineKeyboardButton(text="↩️ К списку", 
                                 callback_data=f"mg_stock_page:{page}")
        ]
    ])
    
    try: await callback.message.delete()
    except Exception: pass
    
    if item.image_url:
        await callback.message.answer_photo(
            item.image_url, caption=text, reply_markup=kb, parse_mode="Markdown"
        )
    else:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

# --- ➕ FSM-КОНСТРУКТОР КАРТОЧКИ ТОВАРА ---

@router.callback_query(F.data == "mg_item_create_start")
async def process_mg_item_create_start(
    callback: CallbackQuery, is_manager: bool, state: FSMContext
):
    if not is_manager: return
    await state.set_state(ManagerShopItemSetup.waiting_for_name)
    await callback.message.answer("📝 **Шаг 1/5:** Введите **Название товара**:")
    await callback.answer()

@router.message(ManagerShopItemSetup.waiting_for_name)
async def process_item_name_input(message: Message, state: FSMContext):
    await state.update_data(item_name=message.text.strip())
    await state.set_state(ManagerShopItemSetup.waiting_for_description)
    await message.answer("📝 **Шаг 2/5:** Введите **Описание товара**:")

@router.message(ManagerShopItemSetup.waiting_for_description)
async def process_item_desc_input(message: Message, state: FSMContext):
    await state.update_data(item_desc=message.text.strip())
    await state.set_state(ManagerShopItemSetup.waiting_for_price)
    await message.answer(f"💰 **Шаг 3/5:** Введите **Цену** в {settings.CURRENCY_NAME} (целое число):")

@router.message(ManagerShopItemSetup.waiting_for_price)
async def process_item_price_input(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите корректное целое число цены:")
        return
    await state.update_data(item_price=int(message.text.strip()))
    await state.set_state(ManagerShopItemSetup.waiting_for_platform)
    
    plat_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌐 Все платформы", callback_data="mg_plat_set:all"),
            InlineKeyboardButton(text="📱 Telegram", callback_data="mg_plat_set:tg"),
            InlineKeyboardButton(text="💬 Discord", callback_data="mg_plat_set:discord")
        ]
    ])
    await message.answer("🌐 **Шаг 4/5:** Выберите **Целевую платформу** для продаж товара:", reply_markup=plat_kb)

# --- 🖼️ ФИНАЛ СОЗДАНИЯ И НОВАЯ МЕХАНИКА СКЛАДА ERP ---

@router.callback_query(
    ManagerShopItemSetup.waiting_for_platform, 
    F.data.startswith("mg_plat_set:")
)
async def process_item_platform_input(callback: CallbackQuery, state: FSMContext):
    plat = callback.data.split(":")
    await state.update_data(item_plat=plat)
    await state.set_state(ManagerShopItemSetup.waiting_for_image)
    
    sk_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить фото", callback_data="mg_skip_photo")]
    ])
    await callback.message.edit_text(
        "🖼️ **Шаг 5/5:** Отправьте **Фотографию товара**.\n"
        "Или нажмите кнопку ниже, чтобы оставить товар без фото:",
        reply_markup=sk_kb
    )
    await callback.answer()

async def save_shop_item_to_db(state: FSMContext, session: AsyncSession, img_id: str = None):
    data = await state.get_data()
    # Авто-детект лотерейного билета по ключевым словам в имени
    name = data.get("item_name")
    is_t = "билет" in name.lower() or "лотерея" in name.lower()
    
    new_item = ShopItem(
        name=name,
        description=data.get("item_desc"),
        price=data.get("item_price"),
        platform_target=data.get("item_plat"),
        is_ticket=is_t,
        image_url=img_id
    )
    session.add(new_item)
    await session.commit()
    await state.clear()

@router.message(ManagerShopItemSetup.waiting_for_image, F.photo)
async def process_item_image_input(message: Message, state: FSMContext, db_session: AsyncSession):
    img_id = message.photo[-1].file_id
    await save_shop_item_to_db(state, db_session, img_id)
    await message.answer("✅ Карточка товара создана! Проверьте её в списке склада.")

@router.callback_query(ManagerShopItemSetup.waiting_for_image, F.data == "mg_skip_photo")
async def process_item_skip_photo(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    await save_shop_item_to_db(state, db_session, None)
    await callback.message.answer("✅ Карточка товара создана (без фото)!")
    await callback.answer()

# --- 📥 ЗАПРАВКА СЕРИЙНИКОВ/МЕРЧА НА СКЛАД (FSM) ---

@router.callback_query(F.data.startswith("mg_stock_load:"))
async def process_mg_stock_load_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    parts = callback.data.split(":")
    item_id = int(parts)
    page = int(parts)
    
    await state.update_data(load_item_id=item_id, load_page=page)
    from bot.states import ManagerStockLoad # Убедись, что стейт добавлен в states.py
    await state.set_state(ManagerStockLoad.waiting_for_units)
    
    await callback.message.answer(
        "📥 **Поштучная заправка Склада [ERP]**\n\n"
        "Отправьте количество штук для мерча (целое число).\n"
        "Либо пришлите **список промокодов/ключей** (каждый код с новой строки):"
    )
    await callback.answer()

@router.message(F.state == "ManagerStockLoad:waiting_for_units")
async def process_mg_stock_load_save(message: Message, state: FSMContext, db_session: AsyncSession):
    data = await state.get_data()
    item_id = data.get("load_item_id")
    page = data.get("load_page")
    text = message.text.strip()
    
    added_count = 0
    if text.isdigit():
        # Режим 1: Обычный вещевой мерч/физический товар
        for _ in range(int(text)):
            unit = StockUnit(item_id=item_id, status="stock", serial_or_promo=None)
            db_session.add(unit)
            added_count += 1
    else:
        # Режим 2: Цифровые промокоды/ключи (построчный разбор)
        codes = [c.strip() for c in text.split("\n") if c.strip()]
        for code in codes:
            unit = StockUnit(item_id=item_id, status="stock", serial_or_promo=code)
            db_session.add(unit)
            added_count += 1
            
    await db_session.commit()
    await state.clear()
    
    await message.answer(f"✅ Успешно оприходовано на Склад: **{added_count}** единиц товара!")

# --- 🛍️ АТОМАРНЫЙ ПЕРЕНОС ТОВАРОВ НА ВИТРИНУ ПУБЛИЧНЫХ ПРОДАЖ ---

@router.callback_query(F.data.startswith("mg_showcase_push:"))
async def process_mg_showcase_push_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    parts = callback.data.split(":")
    item_id = int(parts)
    page = int(parts)
    
    await state.update_data(push_item_id=item_id, push_page=page)
    from bot.states import ManagerShowcasePush
    await state.set_state(ManagerShowcasePush.waiting_for_count)
    await callback.message.answer("🛍️ Введите **количество единиц**, которое нужно перенести со Склада на Витрину:")
    await callback.answer()

@router.message(F.state == "ManagerShowcasePush:waiting_for_count")
async def process_mg_showcase_push_save(message: Message, state: FSMContext, db_session: AsyncSession):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число:")
        return
        
    count_to_push = int(message.text.strip())
    data = await state.get_data()
    item_id = data.get("push_item_id")
    page = data.get("push_page")
    
    # Извлекаем строго свободные единицы со Склада
    units_q = select(StockUnit).where(
        and_(StockUnit.item_id == item_id, StockUnit.status == "stock")
    ).limit(count_to_push)
    units = (await db_session.execute(units_q)).scalars().all()
    
    if len(units) < count_to_push:
        await message.answer(f"❌ На складе недостаточно товара! Доступно всего: **{len(units)}** шт.")
        return
        
    # Переводим в статус витрины
    for u in units:
        u.status = "showcase"
        
    await db_session.commit()
    await state.clear()
    await message.answer(f"✅ Выставлено на Витрину магазина: **{len(units)}** шт. Теперь они доступны к покупке!")

@router.callback_query(F.data.startswith("mg_item_del:"))
async def process_mg_item_delete(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    parts = callback.data.split(":")
    item_id = int(parts)
    page = int(parts)
    
    item = await db_session.get(ShopItem, item_id)
    if item:
        item.is_deleted = True # Мягкое удаление карточки
        await db_session.commit()
        await callback.answer("🗑️ Карточка товара мягко удалена!", show_alert=True)
        
    callback.data = f"mg_stock_page:{page}"
    await cmd_manager_shop_stock_main(callback, is_manager, db_session)
