import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import joinedload
from config import settings
from database.models import ShopItem, StockUnit
from bot.states import (
    ManagerShopItemSetup, 
    ManagerStockLoad, 
    ManagerShowcasePush
)

router = Router(name="manager_shop_inventory_router")
logger = logging.getLogger(__name__)


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

    # ... (Выше идет сбор остатков stock_cnt, showcase_cnt со страницы 4 твоего PDF) ...
    
    p_lbl = "Все" if item.platform_target == "all" else item.platform_target.upper()
    
    # ✅ УМНАЯ ПОДСКАЗКА СТАТУСА: Показывает текущую роль товара в ERP
    ticket_status_lbl = "🎟️ Лотерейный билет" if item.is_ticket else "📦 Обычный товар"
    
    text = (
        f"📦 **Товар: {item.name}**\n\n"
        f"💰 Цена: **{item.price}** {settings.CURRENCY_NAME}\n"
        f"📱 Платформа: `{p_lbl}`\n"
        f"⚙️ Роль в системе: **{ticket_status_lbl}**\n\n" # Изменено тут
        f"📊 **Состояние запасов ERP:**\n"
        f"▪️ В резерве склада: **{stock_cnt}** шт. _(скрыты)_\n"
        f"▪️ На публичной витрине: **{showcase_cnt}** шт. _(в продаже)_\n"
        f"▪️ Всего продано/выдано: **{sold_cnt}** шт.\n\n"
        f"📋 **Описание карточки:**\n_{item.description or 'Нет описания'}_"
    )
    
    # ✅ ИСПРАВЛЕНО: Добавлена No-Code кнопка динамического переключения роли товара
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Загрузить на Склад", callback_data=f"mg_stock_load:{item_id}:{page}"),
            InlineKeyboardButton(text="🚀 Выставить на Витрину", callback_data=f"mg_showcase_push:{item_id}:{page}")
        ],
        [
            # Кнопка-триггер роли билета
            InlineKeyboardButton(text="🔄 Сменить роль (Товар 🔄 Билет)", callback_data=f"mg_item_toggle_ticket:{item_id}:{page}")
        ],
        [
            InlineKeyboardButton(text="❌ Удалить карточку", callback_data=f"mg_item_del:{item_id}:{page}"),
            InlineKeyboardButton(text="↩️ К списку", callback_data=f"mg_stock_page:{page}")
        ]
    ])
    
    try: await callback.message.delete()
    except Exception: pass
    
    if item.image_url:
        await callback.message.answer_photo(item.image_url, caption=text, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("mg_item_toggle_ticket:"))
async def process_mg_item_toggle_ticket(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    """Атомарно инвертирует флаг лотерейного билета для карточки товара."""
    if not is_manager: return
    parts = callback.data.split(":")
    item_id = int(parts[1])
    page = int(parts[2])
    
    item = await db_session.get(ShopItem, item_id)
    if item:
        # Меняем True на False или False на True
        item.is_ticket = not item.is_ticket
        await db_session.commit()
        
        status_text = "назначен ЛОТЕРЕЙНЫМ БИЛЕТОМ" if item.is_ticket else "переведен в разряд ОБЫЧНЫХ ТОВАРОВ"
        await callback.answer(f"✅ Успешно! Товар '{item.name}' {status_text}.", show_alert=True)
        
    # Мгновенно обновляем карточку товара на экране менеджера
    callback.data = f"mg_item_card:{item_id}:{page}"
    await process_mg_item_card_view(callback, is_manager, db_session)


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
            InlineKeyboardButton(text="🗺️ Все платформы", callback_data="mg_plat_set:all"),
            InlineKeyboardButton(text="📱 Telegram", callback_data="mg_plat_set:tg"),
            InlineKeyboardButton(text="🎮 Discord", callback_data="mg_plat_set:discord")
        ]
    ])
    await message.answer(
        "🎁 **Шаг 4/5:** Выберите **Целевую платформу** для продаж товара:", 
        reply_markup=plat_kb
    )

@router.callback_query(
    ManagerShopItemSetup.waiting_for_platform, 
    F.data.startswith("mg_plat_set:")
)
async def process_item_platform_input(callback: CallbackQuery, state: FSMContext):
    # ✅ СТРОГО ИСПРАВЛЕНО: Извлекаем чистую строку по индексу [1] вместо списка целиком
    plat_str = callback.data.split(":")[1]
    await state.update_data(item_plat=plat_str)
    await state.set_state(ManagerShopItemSetup.waiting_for_image)
    
    sk_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить фото", callback_data="mg_skip_photo")]
    ])
    await callback.message.edit_text(
        "🎁 **Шаг 5/5:** Отправьте **Фотографию товара**.\n"
        "Или нажмите кнопку ниже, чтобы оставить товар без фото:",
        reply_markup=sk_kb
    )
    await callback.answer()

async def save_shop_item_to_db(state: FSMContext, session: AsyncSession, img_id: str = None):
    data = await state.get_data()
    name = data.get("item_name")
    is_t = "билет" in name.lower() or "лотерея" in name.lower()
    
    # ✅ СТРОГО СИНХРОНИЗИРОВАНО: Записываем чистую строку платформы из FSM
    new_item = ShopItem(
        name=name,
        description=data.get("item_desc"),
        price=data.get("item_price"),
        platform_target=data.get("item_plat"), # Сюда теперь прилетит "tg" или "discord"
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

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Вернуться на Склад ERP", callback_data="mg_stock_page:1")]
    ])
    await message.answer("✅ Карточка товара создана! Проверьте её в списке склада.")

@router.callback_query(ManagerShopItemSetup.waiting_for_image, F.data == "mg_skip_photo")
async def process_item_skip_photo(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    await save_shop_item_to_db(state, db_session, None)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Вернуться на Склад ERP", callback_data="mg_stock_page:1")]
    ])
    await callback.message.answer("✅ Карточка товара создана (без фото)!")
    await callback.answer()


@router.callback_query(F.data.startswith("mg_stock_load:"))
async def process_mg_stock_load_start(callback: CallbackQuery, is_manager: bool, state: FSMContext, db_session: AsyncSession):
    if not is_manager: return
    parts = callback.data.split(":")
    item_id = int(parts[1])
    page = int(parts[2])
    
    # Атомарно проверяем, какие юниты ОПРИХОДОВАНЫ у этого товара ранее
    check_q = select(StockUnit).where(StockUnit.item_id == item_id).limit(5)
    existing_units = (await db_session.execute(check_q)).scalars().all()
    
    # Определяем текущий No-Code профиль склада для этой карточки
    has_promos = any(u.serial_or_promo is not None for u in existing_units)
    has_merch = any(u.serial_or_promo is None for u in existing_units) if existing_units else False
    
    forced_mode = "any"
    if has_promos and not has_merch:
        forced_mode = "digital"
        prompt = (
            "ℹ️ **Профиль товара: ЦИФРОВОЙ КЛЮЧ / ПРОМОКОД**\n"
            "На складе уже хранятся лицензионные ключи для этой позиции.\n\n"
            "👇 **Подсказка по вводу:**\n"
            "• Пришлите **один код** одной строкой (напр. `STEAM-XXXX`).\n"
            "• Либо пришлите **список кодов**, где каждый новый промокод написан **с новой строки**."
        )
    elif has_merch and not has_promos:
        forced_mode = "physical"
        prompt = (
            "ℹ️ **Профиль товара: ФИЗИЧЕСКИЙ МЕРЧ / РУЧНОЙ ВАУЧЕР**\n"
            "Этот товар ведётся как штучный мерч без кодов.\n\n"
            "👇 **Подсказка по вводу:**\n"
            "• Введите **целое число штук**, которое хотите оприходовать на склад (напр. `15`)."
        )
    else:
        prompt = (
            "📦 **Склад пуст. Выберите формат заправки:**\n\n"
            "• Чтобы заправить **Физический мерч**, введите число штук (напр. `10`).\n"
            "• Чтобы заправить **Цифровые промокоды**, пришлите ключ текстом. "
            "Если кодов много — пишите каждый код с новой строки."
        )

    await state.update_data(load_item_id=item_id, load_page=page, stock_forced_mode=forced_mode)
    await state.set_state(ManagerStockLoad.waiting_for_units)
    
    await callback.message.answer(
        f"📋 **Поштучная заправка Склада [ERP]**\n\n{prompt}"
    )
    await callback.answer()


@router.message(ManagerStockLoad.waiting_for_units)
async def process_mg_stock_load_save(message: Message, state: FSMContext, db_session: AsyncSession):
    data = await state.get_data()
    item_id = data.get("load_item_id")
    page = data.get("load_page")
    forced_mode = data.get("stock_forced_mode", "any")
    raw_text = message.text.strip()
    
    # Проверка ограничений профиля товара
    if forced_mode == "digital" and raw_text.isdigit():
        await message.answer(
            "❌ **Ошибка профиля!** Этот товар ведётся как цифровой промокод.\n"
            "Система ожидает текст ключа (или список кодов построчно), а не число штук. Пожалуйста, введите промокод(ы):"
        )
        return
        
    if forced_mode == "physical" and not raw_text.isdigit():
        await message.answer(
            "❌ **Ошибка профиля!** Этот товар ведётся как физический мерч.\n"
            "Система ожидает целое число штук для добавления на склад. Пожалуйста, введите число:"
        )
        return

    # ВЕТКА 1: Оприходование физического мерча
    if raw_text.isdigit():
        count = int(raw_text)
        for _ in range(count):
            unit = StockUnit(item_id=item_id, status="stock", serial_or_promo=None)
            db_session.add(unit)
            
        await db_session.commit()
        await state.clear() # Для мерча конвейер не нужен, они заливаются пачкой
        
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Вернуться на Склад", callback_data=f"mg_stock_page:{page}")]
        ])
        await message.answer(f"✅ Успешно добавлено на Склад: **{count}** шт. мерча!", reply_markup=back_kb)
        return

    input_codes = [c.strip() for c in raw_text.split("\n") if c.strip()]
    
    if not input_codes:
        await message.answer("❌ Вы прислали пустой текст. Введите промокоды:")
        return

    # 🔍 АТОМАРНАЯ ПРОВЕРКА НА ДУБЛИКАТЫ В БАЗЕ ДАННЫХ
    # Извлекаем все ключи, которые уже привязаны к этому товару
    stmt = select(StockUnit.serial_or_promo).where(
        and_(StockUnit.item_id == item_id, StockUnit.serial_or_promo.in_(input_codes))
    )
    existing_res = await db_session.execute(stmt)
    existing_codes = set(existing_res.scalars().all())
    
    # Разделяем коды на уникальные и дубликаты
    unique_codes = []
    skipped_codes = []
    
    for code in input_codes:
        if code in existing_codes:
            skipped_codes.append(code)
        else:
            unique_codes.append(code)
            
    # Сохраняем строго уникальные новые лицензии
    added_count = 0
    for code in unique_codes:
        unit = StockUnit(item_id=item_id, status="stock", serial_or_promo=code)
        db_session.add(unit)
        added_count += 1
        
    await db_session.commit()
    
    # Формируем No-Code отчет для менеджера
    report_text = f"📥 **Партия успешно обработана!**\n"
    report_text += f"Добавлено новых уникальных ключей: **{added_count}** шт.\n"
    
    if skipped_codes:
        # Обрезаем список для читаемости на экране смартфона
        preview_skipped = skipped_codes[:5]
        skipped_list_str = ", ".join([f"`{c}`" for c in preview_skipped])
        if len(skipped_codes) > 5:
            skipped_list_str += f" и еще {len(skipped_codes) - 5} шт."
            
        report_text += (
            f"\n⚠️ **Внимание! Отфильтровано дубликатов:** **{len(skipped_codes)}** шт.\n"
            f"Эти коды уже использовались или внесены ранее, система их **пропустила**, "
            f"чтобы защитить витрину от скама:\n{skipped_list_str}\n"
        )
        
    loop_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Добавить ещё коды", callback_data=f"mg_stock_loop_more:{item_id}:{page}"),
            InlineKeyboardButton(text="🛑 Хватит, закончить", callback_data=f"mg_stock_loop_stop:{page}")
        ]
    ])
    
    await message.answer(text=report_text, reply_markup=loop_kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("mg_stock_loop_more:"))
async def process_mg_stock_loop_more(callback: CallbackQuery, is_manager: bool):
    """Позволяет остаться в стейте ввода и прислать следующую строку промокода."""
    if not is_manager: return
    await callback.message.edit_text(
        "📝 **Конвейер активен.** Отправьте следующую строку с промокодом "
        "(или пачку кодов, каждый с новой строки):"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mg_stock_loop_stop:"))
async def process_mg_stock_loop_stop(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    """Окончательный выход из конвейера заправки ключей с очисткой FSM."""
    if not is_manager: return
    
    # ✅ СТРОГО ИСПРАВЛЕНО: Меняем индекс [2] на, так как в callback_data всего один знак ":"
    page = int(callback.data.split(":")[1])
    
    await state.clear() # Жестко чистим память FSM только при выходе
    
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Вернуться на Склад", callback_data=f"mg_stock_page:{page}")]
    ])
    await callback.message.edit_text(
        "✅ **Заправка склада успешно завершена!**\nВсе коды зафиксированы в базе данных.",
        reply_markup=back_kb
    )
    await callback.answer()


# --- АТОМАРНЫЙ ПЕРЕНОС ТОВАРОВ НА ВИТРИНУ ПУБЛИЧНЫХ ПРОДАЖ ---

@router.callback_query(F.data.startswith("mg_showcase_push:"))
async def process_mg_showcase_push_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    parts = callback.data.split(":")
    # ✅ СТРОГО ИСПРАВЛЕНО: Добавлены индексы для извлечения строк из списка сплита
    item_id = int(parts[1])
    page = int(parts[2])
    
    await state.update_data(push_item_id=item_id, push_page=page)
    from bot.states import ManagerShowcasePush
    await state.set_state(ManagerShowcasePush.waiting_for_count)
    await callback.message.answer("📥 Введите **количество единиц**, которое нужно перенести со Склада на Витрину:")
    await callback.answer()


@router.message(ManagerShowcasePush.waiting_for_count)
async def process_mg_showcase_push_save(message: Message, state: FSMContext, db_session: AsyncSession):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число:")
        return
        
    count_to_push = int(message.text.strip())
    data = await state.get_data()
    item_id = data.get("push_item_id")
    page = data.get("push_page")
    
    units_q = select(StockUnit).where(
        and_(StockUnit.item_id == item_id, StockUnit.status == "stock")
    ).limit(count_to_push)
    units = (await db_session.execute(units_q)).scalars().all()
    
    if len(units) < count_to_push:
        await message.answer(f"❌ На складе недостаточно товара! Доступно всего: **{len(units)}** шт.")
        return
        
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

@router.callback_query(F.data.startswith("mg_orders_queue:"))
async def cmd_manager_orders_queue(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Вывод реальной очереди необработанных заявок на мерч и крипту с кнопкой архива."""
    if not is_manager: return
    
    page = int(callback.data.split(":")[1])
    limit = 5
    offset = (page - 1) * limit
    
    # Добавлен joinedload(StockUnit.item) для жадной загрузки связей товара
    queue_q = select(StockUnit).options(
        joinedload(StockUnit.item)
    ).where(
        StockUnit.serial_or_promo.like("[ЗАЯВКА]:%")
    ).order_by(StockUnit.updated_at.asc())
    
    # Считаем общее количество заявок в очереди
    total_q = select(func.count(StockUnit.id)).where(
        StockUnit.serial_or_promo.like("[ЗАЯВКА]:%")
    )
    total = (await db_session.execute(total_q)).scalar() or 0
    
    # Запрос выполнится и сразу подтянет ShopItem, исключая MissingGreenlet
    units = (await db_session.execute(
        queue_q.limit(limit).offset(offset)
    )).scalars().all()
    
    text = (
        "📥 **Очередь active заявок на выдачу**\n\n"
        "Сюда попадают физический мерч, требующий отправки, "
        "и ручные ваучеры (TON/крипта), где юзер оставил реквизиты.\n\n"
        f"Всего заявок ожидает обработки: **{total}** шт."
    )
    
    buttons = []
    for u in units:
        item_name = u.item.name if u.item else f"Предмет #{u.item_id}"
        # Вырезаем префикс для короткого превью кнопки
        clean_user_data = u.serial_or_promo.replace("[ЗАЯВКА]:", "").strip()[:15]
        
        buttons.append([
            InlineKeyboardButton(
                text=f"📦 {item_name} | 👤 ID: {u.owner_id} ({clean_user_data}...)",
                callback_data=f"mg_order_manage:{u.id}:{page}"
            )
        ])
        
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_orders_queue:{page-1}"))
    if page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"mg_orders_queue:{page+1}"))
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([
        InlineKeyboardButton(text="📜 Посмотреть архив выдач", callback_data="mg_orders_archive:1")
    ])
        
    buttons.append([InlineKeyboardButton(text="↩️ В корень админки", callback_data="main_menu_manager")])
    
    await callback.message.edit_text(
        text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mg_order_manage:"))
async def process_manager_order_manage_card(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Детальная карточка обработки конкретной заявки с безопасным редиректом."""
    if not is_manager: return
    
    parts = callback.data.split(":")
    unit_id = int(parts[1])
    page = int(parts[2])
    
    unit_q = select(StockUnit).options(joinedload(StockUnit.item)).where(StockUnit.id == unit_id)
    unit = (await db_session.execute(unit_q)).scalar_one_or_none()
    
    # Исправленный безопасный редирект в очередь без мутации frozen-объекта callback.data
    if not unit or not unit.serial_or_promo or not str(unit.serial_or_promo).startswith("[ЗАЯВКА]:"):
        await callback.answer("❌ Заявка уже обработана или не найдена!", show_alert=True)
        
        # Создаем валидный клон объекта через model_copy (для Pydantic v2)
        fake_callback = callback.model_copy(update={"data": f"mg_orders_queue:{page}"})
        await cmd_manager_orders_queue(fake_callback, is_manager, db_session)
        return
        
    item_name = unit.item.name if unit.item else f"Предмет #{unit.item_id}"
    user_reqs = str(unit.serial_or_promo).replace("[ЗАЯВКА]:", "").strip()
    date_str = unit.created_at.strftime('%d.%m.%Y %H:%M') if unit.created_at else "Не указана"
    
    text = (
        f"📥 **Управление заявкой #{unit.id}**\n\n"
        f"🎒 **Что выдать:** {item_name}\n"
        f"👤 **ID получателя:** <code>{unit.owner_id}</code>\n"
        f"📅 **Дата оформления:** {date_str}\n\n"
        f"📋 **Реквизиты / Данные доставки:**\n<code>{user_reqs}</code>\n\n"
        f"👇 После отправки мерча или перевода нажмите кнопку ниже:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выдано / Отправлено", callback_data=f"mg_order_close:{unit_id}:{page}"),
            InlineKeyboardButton(text="↩️ Назад к очереди", callback_data=f"mg_orders_queue:{page}")
        ]
    ])
    
    try:
        await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text=text, reply_markup=kb, parse_mode="HTML")
        try: await callback.message.delete()
        except Exception: pass
            
    await callback.answer()

@router.callback_query(F.data.startswith("mg_order_close:"))
async def process_manager_order_close(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Закрытие заявки менеджером: перевод в архив и уведомление пользователя."""
    if not is_manager: return
    
    parts = callback.data.split(":")
    unit_id = int(parts[1])
    page = int(parts[2])
    
    # Загружаем заявку вместе с данными товара
    unit_q = select(StockUnit).options(joinedload(StockUnit.item)).where(StockUnit.id == unit_id)
    unit = (await db_session.execute(unit_q)).scalar_one_or_none()
    
    if not unit:
        await callback.answer("❌ Заявка не найдена.", show_alert=True)
        return

    user_id = unit.owner_id
    item_name = unit.item.name if unit.item else "Мерч"
    
    # 1. Меняем статус на [ВЫДАНО] внутри текста реквизитов
    old_reqs = str(unit.serial_or_promo).replace("[ЗАЯВКА]:", "").strip()
    unit.serial_or_promo = f"[ВЫДАНО]: {old_reqs}"
    
    # 2. МЕНЯЕМ СТАТУС НА 'archived', чтобы убрать из основного инвентаря юзера!
    unit.status = "archived" 
    
    await db_session.commit()
    
    # 3. ОТПРАВЛЯЕМ ОПОВЕЩЕНИЕ ПОЛЬЗОВАТЕЛЮ
    try:
        await callback.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 **Ваша награда отправлена!**\n\n"
                f"📦 **Предмет:** {item_name}\n"
                f"ℹ️ **Статус:** Заявка успешно обработана менеджером. "
                f"Ожидайте прибытия посылки (СДЭК) или проверяйте ваш криптовалютный кошелек!"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

    await callback.answer("✅ Заявка успешно закрыта и заархивирована!", show_alert=True)
    
    # 4. Безопасный возврат в очередь без мутации frozen-объекта
    fake_callback = callback.model_copy(update={"data": f"mg_orders_queue:{page}"})
    await cmd_manager_orders_queue(fake_callback, is_manager, db_session)


@router.callback_query(F.data.startswith("mg_orders_archive:"))
async def cmd_manager_orders_archive(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Просмотр заархивированных наград менеджером с выводом даты и времени обработки на кнопках."""
    if not is_manager: return
    
    page = int(callback.data.split(":")[1])
    limit = 5
    offset = (page - 1) * limit
    
    # Ищем предметы со статусом archived и меткой [ВЫДАНО]
    archive_q = select(StockUnit).options(joinedload(StockUnit.item)).where(
        and_(StockUnit.status == "archived", StockUnit.serial_or_promo.like("[ВЫДАНО]:%"))
    ).order_by(StockUnit.updated_at.desc())
    
    total_q = select(func.count(StockUnit.id)).where(
        and_(StockUnit.status == "archived", StockUnit.serial_or_promo.like("[ВЫДАНО]:%"))
    )
    total = (await db_session.execute(total_q)).scalar() or 0
    
    units = (await db_session.execute(archive_q.limit(limit).offset(offset))).scalars().all()
    
    text = (
        "📜 **Архив завершенных выдач**\n\n"
        "Ниже представлены все успешно обработанные награды.\n"
        "Нажмите на карточку, чтобы посмотреть полные реквизиты получателя.\n\n"
        f"Всего успешно обработано наград: **{total}** шт."
    )
    
    buttons = []
    for u in units:
        name = u.item.name if u.item else "Предмет"
        
        # ИСПРАВЛЕНО: Форматируем полную дату и время обработки (updated_at) в ДД.ММ | ЧЧ:ММ
        closed_date_time = u.updated_at.strftime('%d.%m | %H:%M') if u.updated_at else "--.-- | --:--"
        
        # Полностью информативная инлайн-кнопка для CRM
        buttons.append([
            InlineKeyboardButton(
                text=f"🗓️ [{closed_date_time}] {name} (ID: {u.id})", 
                callback_data=f"mg_archive_view:{u.id}:{page}"
            )
        ])
        
    # Навигация архива
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text=" Назад", callback_data=f"mg_orders_archive:{page-1}"))
    if page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ", callback_data=f"mg_orders_archive:{page+1}"))
    if nav_row: buttons.append(nav_row)
    
    buttons.append([InlineKeyboardButton(text="↩️ Вернуться к активным", callback_data="mg_orders_queue:1")])
    
    await callback.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()



@router.callback_query(F.data.startswith("mg_archive_view:"))
async def process_manager_archive_view_card(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Детальный просмотр закрытой архивной заявки."""
    if not is_manager: return
    
    parts = callback.data.split(":")
    unit_id = int(parts[1])
    page = int(parts[2])
    
    # Загружаем архивный юнит вместе со связью товара
    unit_q = select(StockUnit).options(joinedload(StockUnit.item)).where(StockUnit.id == unit_id)
    unit = (await db_session.execute(unit_q)).scalar_one_or_none()
    
    if not unit:
        await callback.answer("❌ Запись не найдена в архиве.", show_alert=True)
        return
        
    item_name = unit.item.name if unit.item else f"Предмет #{unit.item_id}"
    # Очищаем реквизиты от технической метки выдачи
    archive_reqs = str(unit.serial_or_promo).replace("[ВЫДАНО]:", "").strip()
    
    created_str = unit.created_at.strftime('%d.%m.%Y %H:%M') if unit.created_at else "Неизвестно"
    closed_str = unit.updated_at.strftime('%d.%m.%Y %H:%M') if unit.updated_at else "Неизвестно"
    
    text = (
        f"📋 **Архивная карточка выдачи #{unit.id}**\n\n"
        f"🎒 **Выданный предмет:** {item_name}\n"
        f"👤 **ID получателя:** <code>{unit.owner_id}</code>\n"
        f"🔍 **Источник получения:** {unit.purchase_source or 'Магазин/Сундук'}\n\n"
        f"📅 **Дата оформления:** {created_str}\n"
        f"✅ **Дата закрытия:** {closed_str}\n\n"
        f"📍 **Реквизиты, по которым была выдача:**\n<code>{archive_reqs}</code>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="↩️ Назад к архиву", callback_data=f"mg_orders_archive:{page}")
        ]
    ])
    
    try:
        await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text=text, reply_markup=kb, parse_mode="HTML")
        try: await callback.message.delete()
        except Exception: pass
        
    await callback.answer()


