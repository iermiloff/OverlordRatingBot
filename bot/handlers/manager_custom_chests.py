import logging
import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import settings
from database.models import User, Order, OrderStatus
from database.connection import AsyncSessionLocal
from bot.states import ManagerCustomChestSetup, ManagerCustomRewardSetup

# ✅ СТРОГО НОВЫЕ МОДЕЛИ БЕТА/RC-ВЕТКИ (замени на свои, если у тебя другие имена таблиц)
from database.models import CustomChest, CustomChestReward

router = Router(name="manager_custom_chests_router")
logger = logging.getLogger(__name__)

# Кэш-блокировщик в памяти процесса для защиты от Race Condition кликов
opened_custom_chests_cache = set()

# --- 📋 ГЛАВНОЕ МЕНЮ И ПАГИНАЦИЯ ---

@router.callback_query(F.data == "cc_main_menu")
@router.callback_query(F.data.startswith("cc_list_page:"))
async def cmd_custom_chests_main(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    # Вычисляем страницу пагинации
    page = 1
    if callback.data.startswith("cc_list_page:"):
        page = int(callback.data.split(":")[1])
        
    limit = 4
    offset = (page - 1) * limit
    
    # Считаем общее число сундуков
    count_q = select(func.count(CustomChest.id))
    total = (await db_session.execute(count_q)).scalar() or 0
    
    # Загружаем сундуки для текущей страницы
    chests_q = select(CustomChest).order_by(CustomChest.created_at.desc()).limit(limit).offset(offset)
    chests = (await db_session.execute(chests_q)).scalars().all()
    
    text = (
        "🧰 **Управление Кастомными Сундуками**\n\n"
        "Здесь вы можете создавать полностью независимые сундуки для ручного сброса в чаты. "
        "Каждый сундук имеет свой текст, картинку и призовой пул наград.\n\n"
        f" Всего создано шаблонов: **{total}** шт."
    )
    
    buttons = []
    
    # Выводим сундуки кнопками
    for cc in chests:
        buttons.append([InlineKeyboardButton(text=f"📦 {cc.name}", callback_data=f"cc_manage:{cc.id}")])
        
    # Стрелки навигации
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cc_list_page:{page-1}"))
    if page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"cc_list_page:{page+1}"))
    if nav_row:
        buttons.append(nav_row)
        
    # Управляющие кнопки корня
    buttons.append([InlineKeyboardButton(text="➕ Создать кастомный сундук", callback_data="cc_create_start")])
    buttons.append([InlineKeyboardButton(text="↩️ Назад в меню админки", callback_data="main_menu_manager")])
    
    await callback.message.delete() # Зачищаем старое медиа перед выводом текста
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

# --- ➕ FSM-КОНСТРУКТОР СОЗДАНИЯ СУНДУКА ---

@router.callback_query(F.data == "cc_create_start")
async def process_cc_create_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerCustomChestSetup.waiting_for_name)
    await callback.message.answer("📝 **Шаг 1/3:** Введите короткое **Название сундука** (для меню админки):")
    await callback.answer()

@router.message(ManagerCustomChestSetup.waiting_for_name)
async def process_cc_name(message: Message, state: FSMContext):
    await state.update_data(cc_name=message.text.strip())
    await state.set_state(ManagerCustomChestSetup.waiting_for_description)
    await message.answer(
        "📝 **Шаг 2/3:** Введите **Описание/Анонс**.\n\n"
        "Этот текст бот опубликует в чате группы при сбросе сундука. "
        "Используйте Markdown для красоты:"
    )

@router.message(ManagerCustomChestSetup.waiting_for_description)
async def process_cc_desc(message: Message, state: FSMContext):
    await state.update_data(cc_desc=message.text.strip())
    await state.set_state(ManagerCustomChestSetup.waiting_for_media)
    
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить медиа (только текст)", callback_data="cc_skip_media")]
    ])
    await message.answer(
        "🖼️ **Шаг 3/3:** Отправьте **Фотографию или GIF-анимацию** для карточки сундука.\n\n"
        "Или нажмите кнопку ниже, чтобы оставить только текстовый анонс:",
        reply_markup=skip_kb
    )

# Вставляем строго под методом process_cc_desc:

@router.message(
    ManagerCustomChestSetup.waiting_for_media, 
    F.photo | F.animation | F.document
)
async def process_cc_media(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    """Прием Фото/GIF на Шаге 3/3 и автоматический переход к наградам."""
    media_id = None
    
    # 1. Проверяем, если прислали обычное фото
    if message.photo:
        media_id = message.photo[-1].file_id
    # 2. Проверяем, если прислали нативную анимацию
    elif message.animation:
        media_id = message.animation.file_id
    # 3. Проверяем, если GIF пришла как документ
    elif message.document:
        mime = message.document.mime_type
        if mime and (mime.startswith("image/") or mime.startswith("video/")):
            media_id = message.document.file_id
            
    if not media_id:
        await message.answer(
            "❌ **Неподдерживаемый формат медиа!**\n"
            "Пожалуйста, отправьте картинку как фото или GIF-анимацию:"
        )
        return

    # Извлекаем текстовые параметры сундука из FSM памяти
    data = await state.get_data()
    
    # Атомарно сохраняем кастомный сундук в PostgreSQL
    new_chest = CustomChest(
        name=data.get("cc_name"),
        description=data.get("cc_desc"),
        media_url=media_id
    )
    db_session.add(new_chest)
    await db_session.commit()
    
    # Запускаем пошаговый цикл настройки призового пула наград
    await start_reward_setup_loop(message, state, new_chest.id)

@router.callback_query(
    ManagerCustomChestSetup.waiting_for_media, 
    F.data == "cc_skip_media"
)
async def process_cc_skip_media(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
):
    """Обработка кнопки пропуска медиа на Шаге 3/3."""
    data = await state.get_data()
    
    # Создаем сундук без картинки (media_url=None)
    new_chest = CustomChest(
        name=data.get("cc_name"),
        description=data.get("cc_desc"),
        media_url=None
    )
    db_session.add(new_chest)
    await db_session.commit()
    
    # Запускаем пошаговую настройку наград
    await start_reward_setup_loop(callback.message, state, new_chest.id)
    await callback.answer()


# --- ➕ ЦИКЛИЧЕСКОЕ ДОБАВЛЕНИЕ НАГРАД (FSM) ---

async def start_reward_setup_loop(msg: Message, state: FSMContext, chest_id: int):
    await state.clear()
    await state.update_data(cc_id=chest_id)
    await state.set_state(ManagerCustomRewardSetup.waiting_for_type)
    
    from bot.keyboards.manager_activities_kb import (
        get_custom_reward_type_keyboard
    )
    await msg.answer(
        f"🎉 **Шаблон сундука сохранен!**\n\n"
        f"Давайте наполним его призовой пул.\n"
        f"**[Шаг 1/3]** Выберите тип награды:",
        reply_markup=get_custom_reward_type_keyboard()
    )

@router.callback_query(
    ManagerCustomRewardSetup.waiting_for_type, 
    F.data.startswith("cc_reward_type:")
)
async def process_cc_reward_type(callback: CallbackQuery, state: FSMContext):
    r_type = callback.data.split(":")
    await state.update_data(r_type=r_type)
    await state.set_state(ManagerCustomRewardSetup.waiting_for_value)
    
    p = (
        f"Введите **количество {settings.CURRENCY_NAME}**:"
        if r_type == "rating" else
        "Введите **название мерча** (напр. _Кепка_):"
    )
    await callback.message.edit_text(
        f"🎁 **Настройка награды [Шаг 2/3]**\n\n{p}", 
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(ManagerCustomRewardSetup.waiting_for_value)
async def process_cc_reward_value(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("r_type") == "rating" and not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число поинтов:")
        return
        
    await state.update_data(r_val=message.text.strip())
    await state.set_state(ManagerCustomRewardSetup.waiting_for_weight)
    await message.answer(
        "🎁 **Настройка награды [Шаг 3/3]**\n\n"
        "Укажите **вес выпадения** (напр. `1.0` или `0.2`):"
    )

@router.message(ManagerCustomRewardSetup.waiting_for_weight)
async def process_cc_reward_weight(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    raw_w = message.text.strip().replace(",", ".")
    try:
        weight = float(raw_w)
        if weight <= 0: raise ValueError
    except ValueError:
        await message.answer("❌ Вес должен быть числом:")
        return
        
    data = await state.get_data()
    chest_id = data.get("cc_id")
    
    new_reward = CustomChestReward(
        chest_id=chest_id,
        reward_type=data.get("r_type"),
        value=data.get("r_val"),
        weight=weight
    )
    db_session.add(new_reward)
    await db_session.commit()
    
    await state.set_state(ManagerCustomRewardSetup.waiting_for_next_decision)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Еще награду", 
                                 callback_data="cc_loop_more"),
            InlineKeyboardButton(text="🛑 Зафиксировать пул", 
                                 callback_data="cc_loop_stop")
        ]
    ])
    await message.answer(
        "✅ Награда добавлена! Внести в этот сундук что-то еще?", 
        reply_markup=kb
    )

@router.callback_query(
    ManagerCustomRewardSetup.waiting_for_next_decision, 
    F.data == "cc_loop_more"
)
async def process_cc_loop_more(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chest_id = data.get("cc_id")
    await state.clear()
    await state.update_data(cc_id=chest_id)
    await state.set_state(ManagerCustomRewardSetup.waiting_for_type)
    
    from bot.keyboards.manager_activities_kb import (
        get_custom_reward_type_keyboard
    )
    await callback.message.edit_text(
        "🎁 **Следующая награда [Шаг 1/3]**:", 
        reply_markup=get_custom_reward_type_keyboard()
    )
    await callback.answer()

@router.callback_query(
    ManagerCustomRewardSetup.waiting_for_next_decision, 
    F.data == "cc_loop_stop"
)
async def process_cc_loop_stop(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
):
    data = await state.get_data()
    chest_id = data.get("cc_id")
    await state.clear()
    
    callback.data = f"cc_manage:{chest_id}"
    await process_cc_manage_card(callback, True, db_session)

# --- 📦 КАРТОЧКА УПРАВЛЕНИЯ СУНДУКОМ ---

@router.callback_query(F.data.startswith("cc_manage:"))
async def process_cc_manage_card(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    chest_id = int(callback.data.split(":"))
    
    chest = await db_session.get(CustomChest, chest_id)
    if not chest:
        await callback.answer("❌ Сундук удален.", show_alert=True)
        return
        
    r_q = select(CustomChestReward).where(
        CustomChestReward.chest_id == chest_id
    )
    rewards = (await db_session.execute(r_q)).scalars().all()
    
    rewards_text = ""
    for idx, r in enumerate(rewards, start=1):
        lbl = "💎 Рейтинг" if r.reward_type == "rating" else "🎒 Мерч"
        rewards_text += f" ▪️ {idx}. {lbl}: *{r.value}* (вес: {r.weight})\n"
        
    text = (
        f"📦 **Кастомный сундук: {chest.name}**\n\n"
        f"📝 **Анонс в чате:**\n_{chest.description}_\n\n"
        f"📊 **Призовой пул:**\n"
        f"{rewards_text or ' _(пул пуст, добавьте награды!)_'}\n"
        f"👇 Выберите действие для контроля:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 СБРОСИТЬ СУНДУК В ЧАТЫ", 
                              callback_data=f"cc_send_now:{chest_id}")],
        [
            InlineKeyboardButton(text="➕ Настроить награды", 
                                 callback_data=f"cc_add_r_rew:{chest_id}"),
            InlineKeyboardButton(text="🗑️ Удалить шаблон", 
                                 callback_data=f"cc_delete:{chest_id}")
        ],
        [InlineKeyboardButton(text="↩️ Вернуться к списку", 
                              callback_data="cc_main_menu")]
    ])
    
    await callback.message.delete()
    if chest.media_url:
        await callback.message.answer_photo(
            chest.media_url, caption=text, reply_markup=kb, 
            parse_mode="Markdown"
        )
    else:
        await callback.message.answer(
            text, reply_markup=kb, parse_mode="Markdown"
        )
    await callback.answer()
@router.callback_query(F.data.startswith("cc_delete:"))
async def process_cc_delete(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    chest_id = int(callback.data.split(":"))
    chest = await db_session.get(CustomChest, chest_id)
    if chest:
        await db_session.delete(chest)
        await db_session.commit()
    await callback.answer("🗑️ Шаблон успешно стерт!", show_alert=True)
    callback.data = "cc_main_menu"
    await cmd_custom_chests_main(callback, is_manager, db_session)

@router.callback_query(F.data.startswith("cc_add_r_rew:"))
async def process_cc_add_r_rew(
    callback: CallbackQuery, is_manager: bool, state: FSMContext
):
    if not is_manager: return
    chest_id = int(callback.data.split(":"))
    await start_reward_setup_loop(callback.message, state, chest_id)
    await callback.answer()

# --- 🚀 РУЧНОЙ ВЫБРОС В ГРУППЫ ---

@router.callback_query(F.data.startswith("cc_send_now:"))
async def process_cc_send_now(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    chest_id = int(callback.data.split(":"))
    
    chest = await db_session.get(CustomChest, chest_id)
    from database.models import ChatConfig
    chats_q = select(ChatConfig).where(ChatConfig.is_active == True)
    chats = (await db_session.execute(chats_q)).scalars().all()
    
    if not chats:
        await callback.answer("❌ Нет активных чатов!", show_alert=True)
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Открыть Кастомный Сундук!", 
                              callback_data=f"cc_user_open:{chest_id}")]
    ])
    
    for chat in chats:
        try:
            if chest.media_url:
                await callback.bot.send_photo(
                    chat_id=chat.id, photo=chest.media_url, 
                    caption=chest.description, reply_markup=kb, 
                    parse_mode="Markdown"
                )
            else:
                await callback.bot.send_message(
                    chat_id=chat.id, text=chest.description, 
                    reply_markup=kb, parse_mode="Markdown"
                )
        except Exception: pass
        
    await callback.answer("🚀 Сундук заброшен в чаты!", show_alert=True)

# --- 👑 КЛИК ОБЫЧНОГО ПОЛЬЗОВАТЕЛЯ (ОТКРЫТИЕ ИЗ ЧАТА) ---

@router.callback_query(F.data.startswith("cc_user_open:"))
async def process_cc_user_open(
    callback: CallbackQuery, db_user: User, db_session: AsyncSession
):
    chest_id = int(callback.data.split(":"))
    msg_id = callback.message.message_id
    
    # 🔒 АТОМАРНАЯ БЛОКИРОВКА В ПАМЯТИ ОТ RACE CONDITION
    unique_lock_key = f"{msg_id}_{chest_id}"
    if unique_lock_key in opened_custom_chests_cache:
        await callback.answer("❌ Ой! Его уже забрали!", show_alert=True)
        return
        
    opened_custom_chests_cache.add(unique_lock_key)
    
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply(
            f"🎁 **Кастомный сундук успешно открыт!**\n\n"
            f"👤 Счастливчик: {callback.from_user.mention_html()}\n"
            f"📥 Награда зачислена в личный кабинет!",
            parse_mode="HTML"
        )
    except Exception:
        opened_custom_chests_cache.discard(unique_lock_key)
        await callback.answer("❌ Ой! Сундук уже забрали!", show_alert=True)
        return
        
    r_q = select(CustomChestReward).where(
        CustomChestReward.chest_id == chest_id
    )
    rewards = (await db_session.execute(r_q)).scalars().all()
    
    if not rewards:
        db_user.current_rating += 20
        db_user.lifetime_rating += 20
        await db_session.commit()
        try: 
            await callback.bot.send_message(
                chat_id=db_user.tg_id, 
                text=f"🎁 Выигрыш: +20 {settings.CURRENCY_NAME}."
            )
        except Exception: pass
        await callback.answer()
        return
        
    population = [r for r in rewards]
    weights = [r.weight for r in rewards]
    win_list = random.choices(population, weights=weights, k=1)
    
    # ИСПРАВЛЕНО: строго берем элемент по индексу 0
    win_reward = win_list
    
    if str(win_reward.reward_type) == "rating":
        amount = int(win_reward.value)
        db_user.current_rating += amount
        db_user.lifetime_rating += amount
        await db_session.commit()
        try: 
            await callback.bot.send_message(
                chat_id=db_user.tg_id, 
                text=f"💎 Твой выигрыш: +{amount} {settings.CURRENCY_NAME}!"
            )
        except Exception: pass
    else:
        new_order = Order(
            user_id=db_user.tg_id, source="custom_chest", 
            item_name=f"[КАСТОМ СУНДУК] {win_reward.value}",
            status=OrderStatus.CREATED.value, 
            delivery_data="Выиграно в кастомном сундуке."
        )
        db_session.add(new_order)
        await db_session.commit()
 
        try:
            await callback.bot.send_message(
                chat_id=db_user.tg_id,
                text=f"🎒 **Вы выиграли мерч:** *{win_reward.value}*",
                parse_mode="Markdown"
            )
        except Exception: pass
        
        for manager_id in settings.managers_list:
            try:
                await callback.bot.send_message(
                    manager_id,
                    text=f"📦 **Кастом Сундук:** @{db_user.username or db_user.tg_id} "
                         f"выиграл *{win_reward.value}*.",
                    parse_mode="Markdown"
                )
            except Exception: pass
            
    await callback.answer()

@router.callback_query(F.data == "cc_cancel")
async def process_cc_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Настройка отменена.")
    await callback.answer()
