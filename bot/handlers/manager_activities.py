import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import settings
from database.models import ChestReward, ChatConfig, User, Order, OrderStatus, SystemSettings
from bot.states import ManagerActivitySetup, ManagerChestSettings
from bot.keyboards.manager_activities_kb import (
    get_activities_main_keyboard,
    get_reward_type_keyboard,
    get_titles_choice_keyboard
)

router = Router(name="manager_activities_router")

# --- СЕРВИСНЫЕ МЕТОДЫ ПАНЕЛИ ---
async def get_sys_settings(session: AsyncSession) -> SystemSettings:
    """Универсальная функция получения глобальных настроек сундука из БД."""
    res = await session.execute(select(SystemSettings).where(SystemSettings.id == 1))
    sys_settings = res.scalar_one_or_none()
    if not sys_settings:
        sys_settings = SystemSettings(
            id=1, chest_open_price=0, chest_min_title_id=1, 
            chest_quiet_hours=15, chest_random_hours=30 # Дефолты в минутах
        )
        session.add(sys_settings)
        await session.commit()
    return sys_settings

@router.message(F.text == "🎁 Настройка Сундука / Розыгрышей")
@router.callback_query(F.data == "mg_activities_panel")
async def cmd_manager_activities(message_or_query, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    sys_settings = await get_sys_settings(db_session)
    
    rewards_result = await db_session.execute(select(ChestReward).order_by(ChestReward.id))
    rewards = rewards_result.scalars().all()
    titles = settings.parsed_titles
    title_info = titles.get(sys_settings.chest_min_title_id)
    title_name = title_info.name if title_info else "Новичок"
    
    rewards_list_text = ""
    if not rewards:
        rewards_list_text = " _(пул пуст, выдается утешительный приз: 15 поинтов)_\n"
    else:
        for idx, r in enumerate(rewards, start=1):
            type_label = "💎 Рейтинг" if r.reward_type == "rating" else "🎒 Мерч"
            rewards_list_text += f" {idx}. {type_label}: *{r.value}* (вес: {r.weight})\n"
            
    # ИСПРАВЛЕНО: Текстовые индикаторы главного меню переведены с «ч» на «мин»
    max_time = sys_settings.chest_quiet_hours + sys_settings.chest_random_hours
    text = (
        "🎁 **Управление игровыми механиками чата**\n\n"
        "📋 **Текущие настройки сундука:**\n"
        f"▪️ Цена открытия: **{sys_settings.chest_open_price}** {settings.CURRENCY_NAME}\n"
        f"▪️ Минимальный титул: **{title_name}**\n"
        f"⏱️ **Алгоритм таймера:** Сундук спит первые **{sys_settings.chest_quiet_hours} мин**, "
        f"а затем случайно выпадает в диапазоне следующих **{sys_settings.chest_random_hours} мин**\n"
        f"_(появится в чате между {sys_settings.chest_quiet_hours} и {max_time} минутами с момента "
        f"прошлого открытия)_\n\n"
        f"📦 **Текущий призовой пул сундука:**\n{rewards_list_text}\n"
        "👇 Используйте кнопки для изменения параметров:"
    )
    
    base_kb = get_activities_main_keyboard()
    back_btn = InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")
    
    has_back = any(btn.callback_data == "main_menu_manager" for row in base_kb.inline_keyboard for btn in row)
    if not has_back:
        base_kb.inline_keyboard.append([back_btn])
        
    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=base_kb, parse_mode="Markdown")
    else:
        try: await message_or_query.message.edit_text(text, reply_markup=base_kb, parse_mode="Markdown")
        except Exception: await message_or_query.answer()

@router.callback_query(F.data == "act_clear_rewards")
async def process_clear_rewards(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await db_session.execute(delete(ChestReward))
    await db_session.commit()
    await callback.answer("✅ Призовой пул сундука полностью очищен!", show_alert=True)
    await cmd_manager_activities(callback, is_manager, db_session)

# --- ПОШАГОВЫЙ ДИАЛОГ НАСТРОЙКИ РАНДОМ-ТАЙМЕРА (FSM) ---

@router.callback_query(F.data == "act_set_timer")
async def process_set_timer_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerChestSettings.waiting_for_quiet_hours)
    
    # ИСПРАВЛЕНО: Текст запроса переведен на МИНУТЫ с примером целого числа
    await callback.message.answer(
        "⏱️ **Настройка таймера [Шаг 1/2]**\n\n"
        "Введите количество **гарантированных МИНУТ тишины** "
        "(время сна сундука, когда он точно не выпадет. Например, `15`):"
    )
    await callback.answer()

@router.message(ManagerChestSettings.waiting_for_quiet_hours)
async def process_quiet_hours_input(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите корректное целое число МИНУТ:")
        return
    await state.update_data(quiet_h=int(message.text.strip()))
    await state.set_state(ManagerChestSettings.waiting_for_random_hours)
    
    # ИСПРАВЛЕНО: Ввод второго шага переведен на МИНУТЫ рандома
    await message.answer(
        "⏱️ **Настройка таймера [Шаг 2/2]**\n\n"
        "Введите **диапазон рандома в МИНУТАХ** "
        "(в течение какого времени после сна сундук имеет шанс выпасть. Например, `30`):"
    )

@router.message(ManagerChestSettings.waiting_for_random_hours)
async def process_random_hours_input(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите корректное целое число МИНУТ:")
        return
 
    data = await state.get_data()
    quiet_h = data.get("quiet_h")
    random_h = int(message.text.strip())
    
    sys_settings = await get_sys_settings(db_session)
    sys_settings.chest_quiet_hours = quiet_h
    sys_settings.chest_random_hours = random_h
    await db_session.commit()
    await state.clear()
    
    # Моментально заставляем воркер пересчитать таймер под новые минуты
    from services.scheduler import calculate_next_chest_time
    import asyncio
    asyncio.create_task(calculate_next_chest_time())
    
    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await message.answer(
        f"✅ Таймер перенастроен! Сундук появится в промежутке "
        f"от {quiet_h} до {quiet_h + random_h} минут.",
        reply_markup=get_back_to_menu_keyboard(to_manager=True)
    )

# --- ИЗМЕНЕНИЕ СТОИМОСТИ КЛЮЧА, ТИТУЛА И ИНТЕРАКТИВЫ ---
@router.callback_query(F.data == "act_set_price")
async def process_set_price_start(
    callback: CallbackQuery, is_manager: bool, state: FSMContext
):
    if not is_manager: return
    await state.set_state(ManagerChestSettings.waiting_for_chest_price)
    await callback.message.answer(
        f" Введите стоимость открытия сундука в {settings.CURRENCY_NAME}:"
    )
    await callback.answer()

@router.message(ManagerChestSettings.waiting_for_chest_price)
async def process_save_price(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число:")
        return
    sys_settings = await get_sys_settings(db_session)
    sys_settings.chest_open_price = int(message.text.strip())
    await db_session.commit()
    await state.clear()
 
    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await message.answer(
        f"✅ Стоимость ключа успешно сохранена!",
        reply_markup=get_back_to_menu_keyboard(to_manager=True)
    )

@router.callback_query(F.data == "act_set_title")
async def process_set_title_start(callback: CallbackQuery, is_manager: bool):
    if not is_manager: return
    await callback.message.answer(
        " Выберите минимальный титул для открытия сундука:", 
        reply_markup=get_titles_choice_keyboard(settings.parsed_titles)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("act_save_title:"))
async def process_save_title(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    title_id = int(callback.data.split(":")[1])
    sys_settings = await get_sys_settings(db_session)
    sys_settings.chest_min_title_id = title_id
    await db_session.commit()
    await callback.answer("✅ Минимальный титул успешно сохранен!", show_alert=True)
    await cmd_manager_activities(callback, is_manager, db_session)

@router.callback_query(F.data == "act_send_chest")
async def process_send_chest_now(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    chats_q = select(ChatConfig).where(ChatConfig.is_active == True)
    active_chats = (await db_session.execute(chats_q)).scalars().all()
 
    if not active_chats:
        await callback.answer(
            "❌Нет подключенных активных чатов!", show_alert=True
        )
        return
    
    chest_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Открыть сундук!", 
                              callback_data="chest_open_click")]
    ])
    for chat in active_chats:
        try:
            await callback.bot.send_message(
                chat_id=chat.id,
                text="⚠️ **ВНИМАНИЕ! В ЧАТЕ ПОЯВИЛСЯ СУНДУК!** ⚠️\n\n"
                     "Кто первый нажмет на кнопку — заберет награду!",
                reply_markup=chest_kb,
                parse_mode="Markdown"
            )
        except Exception: pass
    await callback.answer(f"🚀 Сундук заброшен в чаты!", show_alert=True)

# --- FSM СЦЕНАРИЙ: ДОБАВЛЕНИЕ НАГРАДЫ ---
@router.callback_query(F.data == "act_add_reward")
async def process_add_reward_start(
    callback: CallbackQuery, is_manager: bool, state: FSMContext
):
    if not is_manager: return
    await state.set_state(ManagerActivitySetup.waiting_for_reward_type)
    await callback.message.answer(
        " **Настройка [Шаг 1/3]**\n\nВыбери тип награды:", 
        reply_markup=get_reward_type_keyboard()
    )
    await callback.answer()

@router.callback_query(
    ManagerActivitySetup.waiting_for_reward_type, 
    F.data.startswith("act_type:")
)
async def process_reward_type_choice(
    callback: CallbackQuery, state: FSMContext
):
    """Шаг 2/3: Адаптивный текст подсказки в зависимости от типа награды."""
    # Извлекаем тип (rating или item)
    chosen_type = callback.data.split(":")[1]
    await state.update_data(reward_type=chosen_type)
    await state.set_state(ManagerActivitySetup.waiting_for_reward_value)
 
    # ✅ ИСПРАВЛЕНО: Текст теперь строго разделяется для Валюты и Мерча
    if chosen_type == "rating":
        prompt = (
            f"Введите **количество {settings.CURRENCY_NAME}**, "
            f"которое получит юзер (например: `100`):"
        )
    else:
        prompt = (
            "Введите **название физического мерча** "
            "(например: _Худи с логотипом_):"
        )
        
    await callback.message.edit_text(
        f"🎁 **Настройка сундука [Шаг 2/3]**\n\n{prompt}",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ManagerActivitySetup.waiting_for_reward_value)
async def process_reward_value(message: Message, state: FSMContext):
    """Валидация введенного номинала награды (Валюта или Товар)."""
    data = await state.get_data()
    r_type = data.get("reward_type")
    text_input = message.text.strip()
    
    # ✅ ИСПРАВЛЕНО: Четкая проверка на числовой ввод для типа валюты
    if r_type == "rating" and not text_input.isdigit():
        await message.answer(
            f"❌ **Ошибка ввода!**\n"
            f"Для типа 'Валюта' необходимо ввести корректное "
            f"целое число поинтов. Попробуйте еще раз:"
        )
        return
        
    await state.update_data(reward_value=text_input)
    await state.set_state(ManagerActivitySetup.waiting_for_reward_weight)
    
    await message.answer(
        "🎁 **Настройка сундука [Шаг 3/3]**\n\n"
        "Укажите **математический вес (вероятность)** выпадения "
        "этой награды (например, `1.0` или `0.1`):",
        parse_mode="Markdown"
    )

@router.message(ManagerActivitySetup.waiting_for_reward_weight)
async def process_reward_weight(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    raw_weight = message.text.strip().replace(",", ".")
    try:
        weight = float(raw_weight)
        if weight <= 0: raise ValueError
    except ValueError:
        await message.answer("❌ Ошибка! Вес должен быть положительным числом:")
        return
    data = await state.get_data()
    from database.models import ChestReward
    new_reward = ChestReward(
        reward_type=data.get("reward_type"), 
        value=data.get("reward_value"), 
        weight=weight
    )
    db_session.add(new_reward)
    await db_session.commit()
    await state.clear()
 
    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await message.answer(
        f"✅ Награда успешно добавлена!",
        reply_markup=get_back_to_menu_keyboard(to_manager=True)
    )

@router.callback_query(F.data == "act_cancel")
async def process_act_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание награды отменено.")
    await callback.answer()

# --- КЛИК ПОЛЬЗОВАТЕЛЯ: ОТКРЫТИЕ СУНДУКА В ЧАТЕ ---
@router.callback_query(F.data == "chest_open_click")
async def process_user_open_chest(
    callback: CallbackQuery, db_user: User, db_session: AsyncSession
):
    sys_settings = await get_sys_settings(db_session)
    if db_user.current_rating < sys_settings.chest_open_price:
        await callback.answer(
            f"❌ Недостаточно средств! Цена: {sys_settings.chest_open_price}.", 
            show_alert=True
        )
        return
    titles = settings.parsed_titles
    user_title_id = 1
    for t in sorted(titles.values(), key=lambda x: x.min_rating, reverse=True):
        if db_user.lifetime_rating >= t.min_rating:
            user_title_id = t.id
            break
    if user_title_id < sys_settings.chest_min_title_id:
        req_info = titles.get(sys_settings.chest_min_title_id)
        req_name = req_info.name if req_info else "Продвинутый"
        await callback.answer(
            f"🔒 Требуется титул от '{req_name}' и выше.", show_alert=True
        )
        return
    try:
        await callback.message.edit_text(
            f"🎁 **Секретный сундук успешно открыт!** 🎁\n\n"
            f"👤 Счастливчик: {callback.from_user.mention_html()}\n"
            f"📥 Награда выдана в личный кабинет победителя!",
            reply_markup=None, parse_mode="HTML"
        )
    except Exception:
        await callback.answer("❌ Ой! Кто-то оказался быстрее тебя!", show_alert=True)
        return
    if sys_settings.chest_open_price > 0:
        db_user.current_rating -= sys_settings.chest_open_price
    rewards_result = await db_session.execute(select(ChestReward))
    rewards = rewards_result.scalars().all()
    if not rewards:
        base_rating = 15
        db_user.current_rating += base_rating
        db_user.lifetime_rating += base_rating
        await db_session.commit()
        try: 
            await callback.bot.send_message(
                chat_id=db_user.tg_id, 
                text=f"🎁 Выигрыш: +{base_rating} {settings.CURRENCY_NAME}."
            )
        except Exception: pass
        return
    population = [r for r in rewards]
    weights = [r.weight for r in rewards]
    win_reward = random.choices(population, weights=weights, k=1)
    if win_reward.reward_type == "rating":
        amount = int(win_reward.value)
        db_user.current_rating += amount
        db_user.lifetime_rating += amount
        await db_session.commit()
        try: 
            await callback.bot.send_message(
                chat_id=db_user.tg_id, 
                text=f"💎 Выигрыш: +{amount} {settings.CURRENCY_NAME}!"
            )
        except Exception: pass
    else:
        new_order = Order(
            user_id=db_user.tg_id, source="chest", 
            item_name=f"[СУНДУК] {win_reward.value}", status=OrderStatus.CREATED, 
            delivery_data="Выиграно в сундуке чата."
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
                    text=f"📦 **Сундук:** @{db_user.username or db_user.tg_id} "
                         f"выиграл *{win_reward.value}*.",
                    parse_mode="Markdown"
                )
            except Exception: pass
    await callback.answer()
