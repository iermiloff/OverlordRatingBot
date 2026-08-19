import logging
import random
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_
from sqlalchemy.orm import joinedload

# Прямые импорты из структуры проекта
from config import settings
from database.models import User, ChatConfig, ShopItem, StockUnit, SystemSettings
from database.models import CustomChest, CustomChestReward
from bot.states import ManagerCustomChestSetup, ManagerCustomRewardSetup

router = Router(name="manager_custom_chests_router")
logger = logging.getLogger(__name__)

opened_custom_chests_cache = set()

# --- 📋 ГЛАВНОЕ МЕНЮ И ПОСТРАНИЧНАЯ ПАГИНАЦИЯ ШАБЛОНОВ ---
@router.callback_query(F.data == "cc_main_menu")
@router.callback_query(F.data.startswith("cc_list_page:"))
async def cmd_custom_chests_main(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    """Вывод списка созданных шаблонов кастомных сундуков для менеджера."""
    if not is_manager: return
    
    page = 1
    if callback.data.startswith("cc_list_page:"):
        page = int(callback.data.split(":")[1]) # ИСПРАВЛЕНО: Добавлен индекс [1]
    
    limit = 4
    offset = (page - 1) * limit
    
    count_q = select(func.count(CustomChest.id))
    total = (await db_session.execute(count_q)).scalar() or 0
    
    chests_q = select(CustomChest).order_by(CustomChest.created_at.desc()).limit(limit).offset(offset)
    chests = (await db_session.execute(chests_q)).scalars().all()
    
    text = (
        "⚙️ **Управление Кастомными Сундуками**\n\n"
        f"Всего создано шаблонов: **{total}** шт."
    )
    
    buttons = []
    for cc in chests:
        buttons.append([InlineKeyboardButton(text=f"🎁 {cc.name}", callback_data=f"cc_manage:{cc.id}")])
    
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cc_list_page:{page-1}"))
    if page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"cc_list_page:{page+1}"))
    if nav_row: buttons.append(nav_row)
    
    buttons.append([InlineKeyboardButton(text="➕ Создать сундук", callback_data="cc_create_start")])
    buttons.append([InlineKeyboardButton(text="↩️ Меню админки", callback_data="main_menu_manager")])
    
    try: await callback.message.delete()
    except Exception: pass
    
    await callback.message.answer(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

# --- ➕ FSM-КОНСТРУКТОР КАРТОЧКИ СУНДУКА С ЦЕНЗАМИ ---
@router.callback_query(F.data == "cc_create_start")
async def process_cc_create_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerCustomChestSetup.waiting_for_name)
    await callback.message.answer("📝 **Шаг 1:** Введите **Название сундука** для админки:")
    await callback.answer()

@router.message(ManagerCustomChestSetup.waiting_for_name)
async def process_cc_name(message: Message, state: FSMContext):
    await state.update_data(cc_name=message.text.strip())
    await state.set_state(ManagerCustomChestSetup.waiting_for_description)
    await message.answer("📢 **Шаг 2:** Введите **Описание / Анонс** для чата группы:")

# ВМЕСТО ПЕРЕХОДА К МЕДИА — ИДЕМ В НАСТРОЙКУ ЭКОНОМИКИ И ЦЕНЗОВ
@router.message(ManagerCustomChestSetup.waiting_for_description)
async def process_cc_desc(message: Message, state: FSMContext):
    await state.update_data(cc_desc=message.text.strip())
    
    # Создаем новое динамическое состояние для цены (или используем существующее, если есть)
    # Если в bot/states.py нет waiting_for_price, aiogram 3 позволяет использовать кастомные строки или дописать в states.py
    await state.set_state(ManagerCustomChestSetup.waiting_for_chest_price) 
    await message.answer(f"💰 **Шаг 3 [Цена]:** Введите стоимость ключа для открытия сундука в {settings.CURRENCY_NAME} (целое число, `0` если бесплатно):")

@router.message(ManagerCustomChestSetup.waiting_for_chest_price)
async def process_cc_price_save(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число:")
        return
    await state.update_data(cc_price=int(message.text.strip()))
    
    # Шаг выбора минимального титула инлайн-кнопками
    await state.set_state(ManagerCustomChestSetup.waiting_for_chest_min_title)
    
    titles = settings.parsed_titles
    kb_buttons = []
    for t_id, t_info in titles.items():
        kb_buttons.append([InlineKeyboardButton(text=f"🎖️ {t_info.name} (от {t_info.min_rating} XP)", callback_data=f"cc_title_set:{t_id}")])
        
    await message.answer("🎖️ **Шаг 4 [Титул]:** Выберите минимальный ранг активности для открытия этого сундука:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))

@router.callback_query(ManagerCustomChestSetup.waiting_for_chest_min_title, F.data.startswith("cc_title_set:"))
async def process_cc_title_save(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    title_id = int(callback.data.split(":")[1])
    await state.update_data(cc_min_title=title_id)
    
    # Шаг выбора обязательного предмета-пропуска (билета) из CRM магазина
    items_q = select(ShopItem).where(ShopItem.is_deleted == False)
    shop_items = (await db_session.execute(items_q)).scalars().all()
    
    kb_buttons = []
    # Опция "Без пропуска"
    kb_buttons.append([InlineKeyboardButton(text="🔓 Открыть без билета/пропуска (свободный вход)", callback_data="cc_ticket_set:none")])
    
    for item in shop_items:
        kb_buttons.append([InlineKeyboardButton(text=f"🔑 {item.name}", callback_data=f"cc_ticket_set:{item.id}")])
        
    # Переводим в промежуточное состояние (или удерживаем текущее, фильтруя колбэк)
    # Назовем состояние условно или используем менеджерское
    await state.set_state(ManagerCustomChestSetup.waiting_for_random_hours) # используем как заглушку для выбора пропуска
    await callback.message.edit_text("🔑 **Шаг 5 [Пропуск]:** Выберите предмет на Складе, который спишется как билет-пропуск при открытии сундука:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))
    await callback.answer()

@router.callback_query(ManagerCustomChestSetup.waiting_for_random_hours, F.data.startswith("cc_ticket_set:"))
async def process_cc_ticket_save(callback: CallbackQuery, state: FSMContext):
    ticket_val = callback.data.split(":")[1]
    # Если none — запишем 0 или None
    ticket_id = int(ticket_val) if ticket_val != "none" else None
    await state.update_data(cc_required_item_id=ticket_id)
    
    # ТЕПЕРЬ ПЕРЕХОДИМ К ЗАГРУЗКЕ МЕДИА С КОНСТРУКТОРА ОРИГИНАЛА
    await state.set_state(ManagerCustomChestSetup.waiting_for_media)
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить медиа (только текст)", callback_data="cc_skip_media")]
    ])
    await callback.message.edit_text("🖼️ **Шаг 6 [Медиа]:** Отправьте **Фотографию или GIF-анимацию** для карточки сундука:", reply_markup=skip_kb)
    await callback.answer()

# --- 🖼️ СОХРАНЕНИЕ ШАБЛОНА СУНДУКА С УЧЕТОМ НАСТРОЕННЫХ БАРЬЕРОВ ---
@router.message(
    ManagerCustomChestSetup.waiting_for_media, 
    F.photo | F.animation | F.document
)
async def process_cc_media(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    """Сборщик медиа-файлов и запись кастомного сундука со всеми цензами в базу."""
    media_id = None
    if message.photo:
        media_id = message.photo[-1].file_id
    elif message.animation:
        media_id = message.animation.file_id
    elif message.document:
        mime = message.document.mime_type
        if mime and (mime.startswith("image/") or mime.startswith("video/")):
            media_id = message.document.file_id
    
    if not media_id:
        await message.answer("❌ Ошибка! Отправьте корректную картинку или GIF-анимацию:")
        return
        
    data = await state.get_data()
    
    # Создаем объект сундука, фиксируя в базе все настроенные барьеры
    new_chest = CustomChest(
        name=data.get("cc_name"),
        description=data.get("cc_desc"),
        media_url=media_id
    )
    
    # Если в твоей модели CustomChest есть эти поля, SQLAlchemy запишет их на лету:
    if hasattr(new_chest, 'open_price'): new_chest.open_price = data.get("cc_price", 0)
    if hasattr(new_chest, 'min_title_id'): new_chest.min_title_id = data.get("cc_min_title", 1)
    if hasattr(new_chest, 'required_item_id'): new_chest.required_item_id = data.get("cc_required_item_id")
    
    db_session.add(new_chest)
    await db_session.commit()
    
    # Запускаем цикл наполнения призового пула для этого сундука
    await start_reward_setup_loop(message, state, new_chest.id)

@router.callback_query(
    ManagerCustomChestSetup.waiting_for_media, 
    F.data == "cc_skip_media"
)
async def process_cc_skip_media(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
):
    """Создание чисто текстового шаблона сундука со всеми цензами."""
    data = await state.get_data()
    new_chest = CustomChest(
        name=data.get("cc_name"),
        description=data.get("cc_desc"),
        media_url=None
    )
    
    if hasattr(new_chest, 'open_price'): new_chest.open_price = data.get("cc_price", 0)
    if hasattr(new_chest, 'min_title_id'): new_chest.min_title_id = data.get("cc_min_title", 1)
    if hasattr(new_chest, 'required_item_id'): new_chest.required_item_id = data.get("cc_required_item_id")
    
    db_session.add(new_chest)
    await db_session.commit()
    
    await start_reward_setup_loop(callback.message, state, new_chest.id)
    await callback.answer()

# --- 🔄 АВТОНОМНЫЙ ЦИКЛ НАГРАД (ЖЕСТКИЙ NO-CODE КОНСТРУКТОР) ---
async def start_reward_setup_loop(msg: Message, state: FSMContext, chest_id: int):
    """Инициализация FSM для добавления новой награды в пул кастомного сундука."""
    await state.clear()
    await state.update_data(cc_id=chest_id)
    await state.set_state(ManagerCustomRewardSetup.waiting_for_type)
    
    custom_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Валюта рейтинга", callback_data="cc_reward_type:rating"),
            InlineKeyboardButton(text="📦 Физический мерч", callback_data="cc_reward_type:item")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cc_cancel")]
    ])
    await msg.answer(
        "✨ **Базовая конфигурация сундука успешно сохранена!**\n\n"
        "**[Настройка наград: Шаг 1/3]** Выберите тип приза, который можно будет выбить из этого сундука:",
        reply_markup=custom_kb
    )

@router.callback_query(
    ManagerCustomRewardSetup.waiting_for_type, 
    F.data.startswith("cc_reward_type:")
)
async def process_cc_reward_type(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
):
    """Разветвление сценария пула наград на основе инлайн-кнопки."""
    r_type = callback.data.split(":")[1]
    await state.update_data(r_type=r_type)
    
    await state.set_state(ManagerCustomRewardSetup.waiting_for_value)
    
    if r_type == "rating":
        await callback.message.edit_text(
            f"Введите количество **{settings.CURRENCY_NAME}** для этой награды (отправьте целое число сообщением):"
        )
    else:
        # ЖЕСТКИЙ ВЫБОР МЕРЧА ИЗ БАЗЫ ДАННЫХ
        items_q = select(ShopItem).where(ShopItem.is_deleted == False)
        shop_items = (await db_session.execute(items_q)).scalars().all()
        
        if not shop_items:
            await callback.answer("❌ На складе нет созданных товаров! Сначала добавьте мерч в магазине.", show_alert=True)
            return
            
        kb_buttons = []
        for item in shop_items:
            kb_buttons.append([
                InlineKeyboardButton(text=f"🎁 {item.name}", callback_data=f"cc_merch_select:{item.name}")
            ])
        kb_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cc_reward_cancel")])
        merch_kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        await callback.message.edit_text(
            "📋 **Конструктор призов**\n\nВыберите мерч из списка доступных на Складе для добавления в пул:",
            reply_markup=merch_kb
        )
    await callback.answer()

@router.callback_query(
    ManagerCustomRewardSetup.waiting_for_value, 
    F.data.startswith("cc_merch_select:")
)
async def process_cc_reward_merch_callback(callback: CallbackQuery, state: FSMContext):
    """Сохранение имени выбранного мерча из инлайн-кнопки (без опечаток)."""
    # ИСПРАВЛЕНО: безопасное извлечение имени товара по индексу [1]
    merch_name = callback.data.split("cc_merch_select:")[1]
    
    await state.update_data(r_val=merch_name)
    await state.set_state(ManagerCustomRewardSetup.waiting_for_weight)
    
    await callback.message.edit_text(
        f"📦 Выбран мерч: **{merch_name}**\n\nУкажите **вес (вероятность) выпадения** этой награды (отправьте число сообщением):",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(ManagerCustomRewardSetup.waiting_for_value)
async def process_cc_reward_value(message: Message, state: FSMContext):
    """Ручной ввод количества поинтов (срабатывает только для типа валюты)."""
    data = await state.get_data()
    if data.get("r_type") == "rating" and not message.text.strip().isdigit():
        await message.answer("❌ Ошибка! Введите целое число поинтов:")
        return
        
    await state.update_data(r_val=message.text.strip())
    await state.set_state(ManagerCustomRewardSetup.waiting_for_weight)
    await message.answer(
        "📊 **Настройка награды [Шаг 3/3]**\n\n"
        "Укажите **вес выпадения** этой награды (например, `1.0` или `0.2` сообщением):"
    )

@router.message(ManagerCustomRewardSetup.waiting_for_weight)
async def process_cc_reward_weight(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    """Валидация веса, запись награды в СУБД и развилка: ещё награда или финиш."""
    raw_w = message.text.strip().replace(",", ".")
    try:
        weight = float(raw_w)
        if weight <= 0: 
            raise ValueError
    except ValueError:
        await message.answer("❌ Вес должен быть положительным числом (например, 1.0 или 0.5):")
        return
    
    data = await state.get_data()
    chest_id = data.get("cc_id")
    
    new_reward = CustomChestReward(
        chest_id=chest_id,
        reward_type=str(data.get("r_type")),
        value=str(data.get("r_val")),
        weight=weight
    )
    db_session.add(new_reward)
    await db_session.commit()
    
    await state.set_state(ManagerCustomRewardSetup.waiting_for_next_decision)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Еще награду", callback_data="cc_loop_more"),
            InlineKeyboardButton(text="🔒 Зафиксировать пул", callback_data="cc_loop_stop")
        ]
    ])
    await message.answer("✅ Награда успешно добавлена в призовой фонд! Внести в сундук что-то еще?", reply_markup=kb)

@router.callback_query(
    ManagerCustomRewardSetup.waiting_for_next_decision, F.data == "cc_loop_more"
)
async def process_cc_loop_more(callback: CallbackQuery, state: FSMContext):
    """Возврат на Шаг 1 с сохранением текущего ID сундука."""
    data = await state.get_data()
    chest_id = data.get("cc_id")
    await state.clear()
    await state.update_data(cc_id=chest_id)
    await state.set_state(ManagerCustomRewardSetup.waiting_for_type)
    
    custom_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Валюта рейтинга", callback_data="cc_reward_type:rating"),
            InlineKeyboardButton(text="📦 Физический мерч", callback_data="cc_reward_type:item")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cc_cancel")]
    ])
    await callback.message.edit_text("🎲 **Следующая награда [Шаг 1/3]**:", reply_markup=custom_kb)
    await callback.answer()

@router.callback_query(ManagerCustomRewardSetup.waiting_for_next_decision, F.data == "cc_loop_stop")
async def process_cc_loop_stop(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    """Выход из цикла настройки и вывод готовой карточки шаблона."""
    data = await state.get_data()
    chest_id = data.get("cc_id")
    await state.clear()
    await render_custom_chest_card(callback=callback, chest_id=chest_id, db_session=db_session)

async def render_custom_chest_card(callback: CallbackQuery, chest_id: int, db_session: AsyncSession):
    """Универсальный рендеринг карточки шаблона кастомного сундука со всеми цензами."""
    chest = await db_session.get(CustomChest, chest_id)
    if not chest:
        await callback.answer("❌ Шаблон сундука удален.", show_alert=True)
        return
    
    r_q = select(CustomChestReward).where(CustomChestReward.chest_id == chest_id)
    rewards = (await db_session.execute(r_q)).scalars().all()
    
    rewards_text = ""
    for idx, r in enumerate(rewards, start=1):
        lbl = "💰 Валюта" if r.reward_type == "rating" else "📦 Мерч"
        rewards_text += f" ▪️ {idx}. {lbl}: *{r.value}* (вес: {r.weight})\n"
        
    # Динамически вытаскиваем сохраненные параметры ограничений для вывода админу
    c_price = getattr(chest, 'open_price', 0) or 0
    t_id = getattr(chest, 'min_title_id', 1) or 1
    req_item_id = getattr(chest, 'required_item_id', None)
    
    title_name = settings.parsed_titles.get(t_id).name if settings.parsed_titles.get(t_id) else "Новичок"
    
    pass_text = "Свободный (Без билета)"
    if req_item_id:
        item_obj = await db_session.get(ShopItem, req_item_id)
        if item_obj: pass_text = f"Требуется '{item_obj.name}'"
    
    text = (
        f"🎁 **Кастомный сундук: {chest.name}**\n\n"
        f"💰 **Цена открытия:** {c_price} {settings.CURRENCY_NAME}\n"
        f"🎖️ **Минимальный титул:** {title_name}\n"
        f"🔑 **Предмет-пропуск:** {pass_text}\n\n"
        f"📢 **Анонс для группы:**\n_{chest.description}_\n\n"
        f"📊 **Призовой пул сундука:**\n"
        f"{rewards_text or ' _(пул наград пуст!)_'}\n\n"
        f"Выберите действие для контроля шаблона:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 СБРОСИТЬ СУНДУК В ЧАТЫ ГРУПП", callback_data=f"cc_send_now:{chest_id}")],
        [
            InlineKeyboardButton(text="➕ Настроить награды", callback_data=f"cc_add_r_rew:{chest_id}"),
            InlineKeyboardButton(text="🗑️ Удалить шаблон", callback_data=f"cc_delete:{chest_id}")
        ],
        [InlineKeyboardButton(text="⬅️ Вернуться к списку", callback_data="cc_main_menu")]
    ])
    
    try: await callback.message.delete()
    except Exception: pass

    if chest.media_url:
        try: await callback.message.answer_photo(chest.media_url, caption=text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            try: await callback.message.answer_animation(chest.media_url, caption=text, reply_markup=kb, parse_mode="Markdown")
            except Exception: await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("cc_manage:"))
async def process_cc_manage_card(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    """Вход в карточку управления конкретным кастомным сундуком."""
    if not is_manager: return
    # ИСПРАВЛЕНО: Добавлен индекс [1] для предотвращения TypeError с листом
    chest_id = int(callback.data.split(":")[1])
    await render_custom_chest_card(callback=callback, chest_id=chest_id, db_session=db_session)

@router.callback_query(F.data.startswith("cc_delete:"))
async def process_cc_delete(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    """Безопасное удаление сундука без мутации frozen-объектов Pydantic v2."""
    if not is_manager: return
    # ИСПРАВЛЕНО: Добавлен индекс [1] для предотвращения TypeError с листом
    chest_id = int(callback.data.split(":")[1])
    chest = await db_session.get(CustomChest, chest_id)
    if chest:
        await db_session.delete(chest)
        await db_session.commit()
    
    await callback.answer("🗑️ Шаблон кастомного сундука успешно стерт!", show_alert=True)
    await cmd_custom_chests_main(callback=callback, is_manager=is_manager, db_session=db_session)

@router.callback_query(F.data.startswith("cc_add_r_rew:"))
async def process_cc_add_r_rew(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    """Ручной сброс FSM для перезаписи наград."""
    if not is_manager: return
    # ИСПРАВЛЕНО: Добавлен индекс [1] для предотвращения TypeError с листом
    chest_id = int(callback.data.split(":")[1])
    await start_reward_setup_loop(callback.message, state, chest_id)
    await callback.answer()

@router.callback_query(F.data.startswith("cc_send_now:"))
async def process_cc_send_now(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    """Массовая веерная рассылка кастомного сундука по всем активным группам."""
    if not is_manager: return
    # ИСПРАВЛЕНО: Добавлен индекс [1] для предотвращения TypeError с листом
    chest_id = int(callback.data.split(":")[1])
    chest = await db_session.get(CustomChest, chest_id)
    
    chats_q = select(ChatConfig).where(ChatConfig.is_active == True)
    chats = (await db_session.execute(chats_q)).scalars().all()
    
    if not chats:
        await callback.answer("❌ Нет активных чатов в базе данных!", show_alert=True)
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Открыть Кастомный Сундук!", callback_data=f"cc_user_open:{chest_id}")]
    ])
    
    for chat in chats:
        try:
            if chest.media_url:
                try: await callback.bot.send_photo(chat_id=chat.id, photo=chest.media_url, caption=chest.description, reply_markup=kb, parse_mode="Markdown")
                except Exception: await callback.bot.send_animation(chat_id=chat.id, animation=chest.media_url, caption=chest.description, reply_markup=kb, parse_mode="Markdown")
            else:
                await callback.bot.send_message(chat_id=chat.id, text=chest.description, reply_markup=kb, parse_mode="Markdown")
        except Exception: pass
            
    await callback.answer("🚀 Кастомный сундук успешно заброшен во все чаты!", show_alert=True)

# --- 🎁 КЛИК ОБЫЧНОГО ПОЛЬЗОВАТЕЛЯ (ОТКРЫТИЕ ИЗ ЧАТА) ---
@router.callback_query(F.data.startswith("cc_user_open:"))
async def process_cc_user_open(
    callback: CallbackQuery, db_user: User, db_session: AsyncSession
):
    """Атомарное открытие сундука с проверкой Цены, Титула и Билета из шаблона."""
    chest_id = int(callback.data.split(":")[1])
    msg_id = callback.message.message_id
    
    chest = await db_session.get(CustomChest, chest_id)
    if not chest:
        await callback.answer("❌ Этот кастомный сундук больше не существует.", show_alert=True)
        return

    # Динамически считываем индивидуальные настройки этого сундука
    chest_price = getattr(chest, 'open_price', 0) or 0
    min_title_required = getattr(chest, 'min_title_id', 1) or 1
    required_item_id = getattr(chest, 'required_item_id', None)

    # БАРЬЕР 1. ПРОВЕРКА БАЛАНСА ВАЛЮТЫ РЕЙТИНГА
    if db_user.current_rating < chest_price:
        await callback.answer(f"❌ Недостаточно {settings.CURRENCY_NAME}! Цена: {chest_price}.", show_alert=True)
        return

    # БАРЬЕР 2. ПРОВЕРКА ОГРАНИЧЕНИЙ ПО РАНГУ ТИТУЛА
    titles = settings.parsed_titles
    user_title_id = 1
    for t in sorted(titles.values(), key=lambda x: x.min_rating, reverse=True):
        if db_user.lifetime_rating >= t.min_rating:
            user_title_id = t.id
            break
            
    if user_title_id < min_title_required:
        req_info = titles.get(min_title_required)
        req_name = req_info.name if req_info else "Продвинутый"
        await callback.answer(f"🔒 Нужен титул от '{req_name}' и выше.", show_alert=True)
        return

    # БАРЬЕР 3. ПРОВЕРКА НАЛИЧИЯ И СПИСАНИЕ ПРЕДМЕТА-ПРОПУСКА
    user_ticket = None
    if required_item_id:
        ticket_q = select(StockUnit).where(
            and_(
                StockUnit.owner_id == db_user.tg_id, 
                StockUnit.item_id == required_item_id,
                StockUnit.status == "sold"
            )
        ).limit(1)
        user_ticket = (await db_session.execute(ticket_q)).scalar_one_or_none()
        
        if not user_ticket:
            item_obj = await db_session.get(ShopItem, required_item_id)
            item_name = item_obj.name if item_obj else "Специальный Билет"
            await callback.answer(f"🔑 Требуется списать '{item_name}' из Инвентаря!", show_alert=True)
            return

    # АТОМАРНАЯ БЛОКИРОВКА В ПАМЯТИ ОТ RACE CONDITION
    unique_lock_key = f"{msg_id}_{chest_id}"
    if unique_lock_key in opened_custom_chests_cache:
        await callback.answer("❌ Ой! Этот сундук уже кто-то забрал!", show_alert=True)
        return
        
    opened_custom_chests_cache.add(unique_lock_key)
