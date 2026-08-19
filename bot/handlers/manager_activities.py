import random
import logging
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_

from config import settings
# ✅ ИСПРАВЛЕНО: Легаси-модели Order вырезаны из СУБД ядра
from database.models import (
    ChestReward, ChatConfig, User, 
    SystemSettings, StockUnit, ShopItem
)
from bot.states import (
    ManagerActivitySetup, 
    ManagerChestSettings
)
from bot.keyboards.manager_activities_kb import (
    get_activities_main_keyboard,
    get_reward_type_keyboard,
    get_titles_choice_keyboard
)

opened_chests_cache = set()
router = Router(name="manager_activities_router")
logger = logging.getLogger(__name__)

async def get_sys_settings(
    session: AsyncSession
) -> SystemSettings:
    """Универсальная функция получения глобальных настроек."""
    res = await session.execute(
        select(SystemSettings).where(SystemSettings.id == 1)
    )
    sys_settings = res.scalar_one_or_none()
    if not sys_settings:
        sys_settings = SystemSettings(
            id=1, chest_open_price=0, chest_min_title_id=1, 
            chest_quiet_hours=15, chest_random_hours=30
        )
        session.add(sys_settings)
        await session.commit()
    return sys_settings

@router.message(F.text == "🎁 Настройка Сундука / Розыгрышей")
@router.callback_query(F.data == "mg_activities_panel")
async def cmd_manager_activities(
    message_or_query, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    
    sys_settings = await get_sys_settings(db_session)
    
    rewards_res = await db_session.execute(
        select(ChestReward).order_by(ChestReward.id)
    )
    rewards = rewards_res.scalars().all()
    titles = settings.parsed_titles
    title_info = titles.get(sys_settings.chest_min_title_id)
    title_name = title_info.name if title_info else "Новичок"
    
    rewards_list_text = ""
    if not rewards:
        rewards_list_text = " _(пул пуст, приз: 15 поинтов)_\n"
    else:
        for idx, r in enumerate(rewards, start=1):
            type_lbl = (
                "💎 Рейтинг" if str(r.reward_type) == "rating" 
                else "🎒 Мерч"
            )
            rewards_list_text += (
                f" {idx}. {type_lbl}: *{r.value}* "
                f"(вес: {r.weight})\n"
            )
            
    max_time = (
        sys_settings.chest_quiet_hours + 
        sys_settings.chest_random_hours
    )
    text = (
        "🎁 **Управление игровыми механиками чата**\n\n"
        "📝 **Текущие настройки сундука:**\n"
        f"▪️ Цена открытия: **{sys_settings.chest_open_price}** "
        f"{settings.CURRENCY_NAME}\n"
        f"▪️ Минимальный титул: **{title_name}**\n"
        f"⏱️ **Алгоритм таймера:** Сундук спит первые "
        f"**{sys_settings.chest_quiet_hours} мин**, а затем "
        f"выпадает в диапазоне следующих "
        f"**{sys_settings.chest_random_hours} мин**\n"
        f"_(между {sys_settings.chest_quiet_hours} и "
        f"{max_time} минутами)_\n\n"
        f"📊 **Призовой пул:**\n{rewards_list_text}\n"
        "👇 Используйте кнопки для изменения параметров:"
    )
    
    base_kb = get_activities_main_keyboard()
    back_btn = InlineKeyboardButton(
        text="↩️ Главное меню админки", 
        callback_data="main_menu_manager"
    )
    
    has_back = any(
        btn.callback_data == "main_menu_manager" 
        for row in base_kb.inline_keyboard for btn in row
    )
    if not has_back:
        base_kb.inline_keyboard.append([back_btn])
        
    if isinstance(message_or_query, Message):
        await message_or_query.answer(
            text, reply_markup=base_kb, parse_mode="Markdown"
        )
    else:
        try: 
            await message_or_query.message.edit_text(
                text, reply_markup=base_kb, parse_mode="Markdown"
            )
        except Exception: pass

# --- ⚙️ ПОШАГОВЫЕ НАСТРОЙКИ СУНДУКА (FSM) ---

@router.callback_query(F.data == "act_add_reward")
async def process_add_reward_start(
    callback: CallbackQuery, is_manager: bool, state: FSMContext
):
    if not is_manager: return
    await state.set_state(
        ManagerActivitySetup.waiting_for_reward_type
    )
    await callback.message.answer(
        "🎁 **Настройка [Шаг 1/3]**\n\nВыбери тип награды:", 
        reply_markup=get_reward_type_keyboard()
    )
    await callback.answer()

@router.callback_query(
    ManagerActivitySetup.waiting_for_reward_type, 
    F.data.startswith("act_type:")
)
async def process_reward_type_choice(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
):
    # ИСПРАВЛЕНО: берем элемент с индексом, чтобы получить чистую строку "rating" или "merch"
    chosen_type = callback.data.split(":")[1] 
    await state.update_data(reward_type=chosen_type)
    
    # Переводим в состояние ожидания значения
    await state.set_state(ManagerActivitySetup.waiting_for_reward_value)
    
    if chosen_type == "rating":
        prompt = (
            f"Введите **количество {settings.CURRENCY_NAME}**, "
            f"которое получит юзер (целое число):"
        )
        await callback.message.edit_text(
            f" **Настройка сундука [Шаг 2/3]**\n\n{prompt}", 
            parse_mode="Markdown"
        )
    else:
        # Жесткий выбор мерча из базы данных
        items_q = select(ShopItem).where(ShopItem.is_deleted == False)
        shop_items = (await db_session.execute(items_q)).scalars().all()
        
        if not shop_items:
            await callback.answer("❌ На складе нет созданных товаров! Сначала добавьте мерч в CRM магазина.", show_alert=True)
            await state.clear()
            return
            
        # Строим инлайн-клавиатуру из существующих на складе товаров
        kb_buttons = []
        for item in shop_items:
            kb_buttons.append([
                InlineKeyboardButton(text=f"📦 {item.name}", callback_data=f"act_merch_select:{item.name}")
            ])
        kb_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="act_cancel")])
        merch_kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
        await callback.message.edit_text(
            " **Настройка сундука [Шаг 2/3]**\n\nВыберите **товар/мерч** из списка существующих на Складе:",
            reply_markup=merch_kb
        )
    
    # Гарантированно гасим часики анимации на кнопке
    await callback.answer()


# ХЭНДЛЕР ДЛЯ ПЕРЕХВАТА КЛИКА ПО МЕРЧУ (Тут тоже исправлено расщепление строки!)
@router.callback_query(
    ManagerActivitySetup.waiting_for_reward_value, 
    F.data.startswith("act_merch_select:")
)
async def process_reward_merch_callback(callback: CallbackQuery, state: FSMContext):
    # ИСПРАВЛЕНО: забираем точное имя мерча после двоеточия
    merch_name = callback.data.split(":")[1]
    
    await state.update_data(reward_value=merch_name)
    await state.set_state(ManagerActivitySetup.waiting_for_reward_weight)
    
    await callback.message.edit_text(
        f" Выбран мерч: **{merch_name}**\n\n**Настройка [Шаг 3/3]**\nУкажите **вес выпадения** сундука (отправьте число сообщением):",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(ManagerActivitySetup.waiting_for_reward_value)
async def process_reward_value(message: Message, state: FSMContext):
    data = await state.get_data()
    r_type = data.get("reward_type")
    text_input = message.text.strip()
    if r_type == "rating" and not text_input.isdigit():
        await message.answer("❌ Введите целое число:")
        return
    await state.update_data(reward_value=text_input)
    await state.set_state(
        ManagerActivitySetup.waiting_for_reward_weight
    )
    await message.answer(
        "🎁 **Настройка [Шаг 3/3]**\n\nУкажите **вес выпадения**:"
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
        await message.answer("❌ Ошибка! Вес должен быть числом:")
        return
        
    data = await state.get_data()
    new_reward = ChestReward(
        reward_type=str(data.get("reward_type")), 
        value=data.get("reward_value"), 
        weight=weight
    )
    db_session.add(new_reward)
    await db_session.commit()
    await state.clear()
    
    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await message.answer(
        "✅ Награда успешно добавлена в призовой пул!", 
        reply_markup=get_back_to_menu_keyboard(to_manager=True)
    )

@router.callback_query(F.data == "act_set_timer")
async def process_set_timer_start(
    callback: CallbackQuery, is_manager: bool, state: FSMContext
):
    if not is_manager: return
    await state.set_state(
        ManagerChestSettings.waiting_for_quiet_hours
    )
    await callback.message.answer(
        "⏱️ **Настройка таймера [Шаг 1/2]**\n\n"
        "Введите количество **МИНУТ тишины** (напр. `15`):"
    )
    await callback.answer()

@router.message(ManagerChestSettings.waiting_for_quiet_hours)
async def process_quiet_hours_input(
    message: Message, state: FSMContext
):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число МИНУТ:")
        return
    await state.update_data(quiet_h=int(message.text.strip()))
    await state.set_state(
        ManagerChestSettings.waiting_for_random_hours
    )
    await message.answer(
        "⏱️ **Настройка таймера [Шаг 2/2]**\n\n"
        "Введите **диапазон рандома в МИНУТАХ** (напр. `30`):"
    )

@router.message(ManagerChestSettings.waiting_for_random_hours)
async def process_random_hours_input(
    message: Message, state: FSMContext, db_session: AsyncSession
):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число МИНУТ:")
        return
    data = await state.get_data()
    quiet_h = data.get("quiet_h")
    random_h = int(message.text.strip())
    
    sys_settings = await get_sys_settings(db_session)
    sys_settings.chest_quiet_hours = quiet_h
    sys_settings.chest_random_hours = random_h
    await db_session.commit()
    await state.clear()
    
    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await message.answer(
        f"✅ Таймер изменен! Диапазон: от {quiet_h} до "
        f"{quiet_h + random_h} минут.\n\n"
        f"Планировщик применит настройки автоматически!",
        reply_markup=get_back_to_menu_keyboard(to_manager=True)
    )

@router.callback_query(F.data == "act_set_price")
async def process_set_price_start(
    callback: CallbackQuery, is_manager: bool, state: FSMContext
):
    if not is_manager: return
    await state.set_state(
        ManagerChestSettings.waiting_for_chest_price
    )
    await callback.message.answer(
        f"💰 Введите стоимость ключа в {settings.CURRENCY_NAME}:"
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
        "✅ Стоимость ключа сохранена!", 
        reply_markup=get_back_to_menu_keyboard(to_manager=True)
    )

@router.callback_query(F.data == "act_set_title")
async def process_set_title_start(
    callback: CallbackQuery, is_manager: bool
):
    if not is_manager: return
    await callback.message.answer(
        "🎖️ Выберите минимальный титул для открытия сундука:", 
        reply_markup=get_titles_choice_keyboard(
            settings.parsed_titles
        )
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
    await callback.answer("✅ Минимальный титул сохранен!", show_alert=True)
    await cmd_manager_activities(callback, is_manager, db_session)

@router.callback_query(F.data == "act_send_chest")
async def process_send_chest_now(
    callback: CallbackQuery, is_manager: bool, db_session: AsyncSession
):
    if not is_manager: return
    chats_q = select(ChatConfig).where(ChatConfig.is_active == True)
    active_chats = (await db_session.execute(chats_q)).scalars().all()
    if not active_chats:
        await callback.answer("❌ Нет активных чатов!", show_alert=True)
        return
        
    chest_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Открыть сундук!", 
                              callback_data="chest_open_click")]
    ])
    for chat in active_chats:
        try:
            await callback.bot.send_message(
                chat_id=chat.id,
                text="📦 **ВНИМАНИЕ! В ЧАТЕ ПОЯВИЛСЯ СУНДУК!** 📦\n\n"
                     "Кто первый нажмет на кнопку — заберет награду!",
                reply_markup=chest_kb, parse_mode="Markdown"
            )
        except Exception: pass
    await callback.answer("🚀 Сундук заброшен в чаты!", show_alert=True)

@router.callback_query(F.data == "act_cancel")
async def process_act_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание награды отменено.")
    await callback.answer()

# --- 👑 КЛИК ОБЫЧНОГО ПОЛЬЗОВАТЕЛЯ (ОТКРЫТИЕ СУНДУКА АКТИВНОСТИ) ---

@router.callback_query(F.data == "chest_open_click")
async def process_user_open_chest(
    callback: CallbackQuery, db_user: User, db_session: AsyncSession
):
    """Атомарное открытие сундука активности из чата группы."""
    sys_settings = await get_sys_settings(db_session)
    msg_id = callback.message.message_id

    # 1. МГНОВЕННАЯ АТОМАРНАЯ ПРОВЕРКА БЛОКИРОВКИ ОТ RACE CONDITION
    if msg_id in opened_chests_cache:
        await callback.answer(
            "❌ Ой! Кто-то оказался быстрее тебя и уже забрал приз!", 
            show_alert=True
        )
        return

    # Проверка баланса кошелька для открытия
    if db_user.current_rating < sys_settings.chest_open_price:
        await callback.answer(
            f"❌ Недостаточно средств! Цена ключа: "
            f"{sys_settings.chest_open_price}.", 
            show_alert=True
        )
        return

    # Проверка ограничений по рангу активности
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
            f"🔒 Доступ ограничен! Нужен титул от '{req_name}' и выше.", 
            show_alert=True
        )
        return

    # 2. ЖЕСТКАЯ БЛОКИРОВКА В ПАМЯТИ ПРОЦЕССА ВЫИГРЫША
    opened_chests_cache.add(msg_id)

    try:
        # Убираем инлайн-кнопку с экрана для фиксации финиша
        await callback.message.edit_text(
            f"🎁 **Секретный сундук успешно открыт!** 🎁\n\n"
            f"👤 Счастливчик: {callback.from_user.mention_html()}\n"
            f"📥 Награда зачислена в личный кабинет победителя!",
            reply_markup=None, parse_mode="HTML"
        )
    except Exception:
        # Снимаем бронь, если Telegram выдал ошибку совпадения миллисекунд клика
        if msg_id in opened_chests_cache:
            opened_chests_cache.discard(msg_id)
        await callback.answer(
            "❌ Ой! Кто-то оказался быстрее тебя!", show_alert=True
        )
        return

    # Списание стоимости ключа
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
                text=f"🎁 Твой выигрыш: +{base_rating} {settings.CURRENCY_NAME}."
            )
        except Exception: pass
        await callback.answer()
        return
        
    population = [r for r in rewards]
    weights = [r.weight for r in rewards]
    win_list = random.choices(population, weights=weights, k=1)
    
    # СТРОГО ИСПРАВЛЕНО: Извлекаем ChestReward из списка по индексу 0
    win_reward = win_list[0]
    
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
        # Режим Б: Мерч. Находим свободный StockUnit по имени товара на Складе ERP
        item_q = select(ShopItem).where(
            and_(ShopItem.name == win_reward.value, ShopItem.is_deleted == False)
        ).limit(1)
        shop_item = (await db_session.execute(item_q)).scalar_one_or_none()
        
        if shop_item:
            # Ищем ровно одну поштучную единицу товара на Складе (статус stock)
            unit_q = select(StockUnit).where(
                and_(StockUnit.item_id == shop_item.id, StockUnit.status == "stock")
            ).limit(1)
            unit = (await db_session.execute(unit_q)).scalar_one_or_none()
            
            if unit:
                # ✅ ИСПРАВЛЕНО: Привязка по поштучному ID StockUnit без легаси таблиц
                unit.status = "won"
                unit.owner_id = db_user.tg_id
                unit.purchase_source = "chest"
                await db_session.commit()
                
                try:
                    await callback.bot.send_message(
                        chat_id=db_user.tg_id,
                        text=f"🎒 **Вы выиграли мерч:** *{shop_item.name}*\n"
                             f"Уникальный ID предмета: `{unit.id}`. "
                             f"Проверить можно в вашем Инвентаре!",
                        parse_mode="Markdown"
                    )
                except Exception: pass
                
                for manager_id in settings.managers_list:
                    try:
                        await callback.bot.send_message(
                            manager_id,
                            text=f"📦 **Сундук активности:** "
                                 f"@{db_user.username or db_user.tg_id} "
                                 f"выиграл мерч *{shop_item.name}* "
                                 f"(Единица ID: {unit.id}).",
                            parse_mode="Markdown"
                        )
                    except Exception: pass
                await callback.answer()
                return

        # Фолбек-компенсация: если админ забыл оприходовать мерч на Склад
        fallback_coins = 50
        db_user.current_rating += fallback_coins
        db_user.lifetime_rating += fallback_coins
        await db_session.commit()
        try:
            await callback.bot.send_message(
                chat_id=db_user.tg_id,
                text=f"🎁 Вы выиграли мерч *{win_reward.value}*, но его "
                     f"не оказалось в наличии на Складе!\n"
                     f"Вам зачислена монетарная компенсация: "
                     f"+{fallback_coins} {settings.CURRENCY_NAME}!",
                parse_mode="Markdown"
            )
        except Exception: pass

    await callback.answer()


