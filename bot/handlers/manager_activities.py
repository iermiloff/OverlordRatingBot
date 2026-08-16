import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

# Импорты конфигурации, моделей и клавиатур
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
        sys_settings = SystemSettings(id=1, chest_open_price=0, chest_min_title_id=1)
        session.add(sys_settings)
        await session.commit()
    return sys_settings

@router.message(F.text == "🎁 Настройка Сундука / Розыгрышей")
async def cmd_manager_activities(message: Message, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    sys_settings = await get_sys_settings(db_session)
    count_q = select(func.count(ChestReward.id))
    total_rewards = (await db_session.execute(count_q)).scalar()

    titles = settings.parsed_titles
    title_info = titles.get(sys_settings.chest_min_title_id)
    title_name = title_info.name if title_info else "Новичок"

    text = (
        "🎁 **Управление игровыми механиками чата**\n\n"
        "Здесь вы можете настраивать интерактив in группах без кодинга и SSH.\n\n"
        f"📋 **Текущие настройки сундука:**\n"
        f"▪️ Цена открытия: **{sys_settings.chest_open_price}** {settings.CURRENCY_NAME}\n"
        f"▪️ Минимальный титул: **{title_name}**\n"
        f"📦 Уникальных наград in пуле: **{total_rewards}**\n\n"
        "👇 Используйте кнопки для изменения параметров или запуска интерактивов:"
    )
    await message.answer(text, reply_markup=get_activities_main_keyboard(), parse_mode="Markdown")

@router.callback_query(F.data == "act_clear_rewards")
async def process_clear_rewards(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    from sqlalchemy import delete
    await db_session.execute(delete(ChestReward))
    await db_session.commit()
    await callback.answer("✅ Призовой пул сундука полностью очищен!", show_alert=True)
    await cmd_manager_activities(callback.message, is_manager, db_session)
    try: await callback.message.delete()
    except Exception: pass

# --- СТАРТ НАСТРОЕК СУНДУКА (ЦЕНА И ТИТУЛ) ---

@router.callback_query(F.data == "act_set_price")
async def process_set_price_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerChestSettings.waiting_for_chest_price)
    await callback.message.answer(f"💳 **Введите новую стоимость открытия сундука** in валюте {settings.CURRENCY_NAME} (целое число):")
    await callback.answer()

@router.message(ManagerChestSettings.waiting_for_chest_price)
async def process_save_price(message: Message, state: FSMContext, db_session: AsyncSession):
    text_input = message.text.strip()
    if not text_input.isdigit():
        await message.answer("❌ Ошибка! Введите корректное целое число:")
        return

    sys_settings = await get_sys_settings(db_session)
    sys_settings.chest_open_price = int(text_input)
    await db_session.commit()
    await state.clear()

    await message.answer(f"✅ Стоимость открытия сундука успешно изменена на **{text_input}** {settings.CURRENCY_NAME}!")
    await cmd_manager_activities(message, is_manager=True, db_session=db_session)

@router.callback_query(F.data == "act_set_title")
async def process_set_title_start(callback: CallbackQuery, is_manager: bool):
    if not is_manager: return
    titles = settings.parsed_titles
    await callback.message.answer(
        "🎖️ **Выберите минимальный титул**, начиная с которого пользователи смогут открывать сундук:",
        reply_markup=get_titles_choice_keyboard(titles)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("act_save_title:"))
async def process_save_title(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    title_id = int(callback.data.split(":"))

    sys_settings = await get_sys_settings(db_session)
    sys_settings.chest_min_title_id = title_id
    await db_session.commit()

    titles = settings.parsed_titles
    new_title_name = titles.get(title_id).name

    await callback.answer(f"✅ Требуемый титул изменен на '{new_title_name}'!", show_alert=True)
    await cmd_manager_activities(callback.message, is_manager, db_session)
    try: await callback.message.delete()
    except Exception: pass

# --- МЕХАНИКА: ПРИНУДИТЕЛЬНЫЙ ВЫБРОС СУНДУКА ---

@router.callback_query(F.data == "act_send_chest")
async def process_send_chest_now(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    chats_result = await db_session.execute(select(ChatConfig).where(ChatConfig.is_active == True))
    active_chats = chats_result.scalars().all()
    
    if not active_chats:
        await callback.answer("❌ Нет подключенных активных чатов для отправки сундука!", show_alert=True)
        return

    sent_count = 0
    chest_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Открыть сундук!", callback_data="chest_open_click")]
    ])

    for chat in active_chats:
        try:
            await callback.bot.send_message(
                chat_id=chat.id,
                text="📦 **ВНИМАНИЕ! В ЧАТЕ ПОЯВИЛСЯ СЕКРЕТНЫЙ СУНДУК!** 📦\n\n"
                     "Кто первый нажмет на кнопку ниже, тот и заберет случайную награду! Погнали! 👇",
                reply_markup=chest_kb,
                parse_mode="Markdown"
            )
            sent_count += 1
        except Exception: pass

    await callback.answer(f"🚀 Сундук заброшен в {sent_count} чат(ов)!", show_alert=True)

# --- МЕХАНИКА: МГНОВЕННЫЙ РОЗЫГРЫШ ---

@router.callback_query(F.data == "act_run_giveaway")
async def process_run_giveaway(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    query = select(User).where(User.lifetime_rating > 10).order_by(func.random()).limit(1)
    result = await db_session.execute(query)
    winner = result.scalar_one_or_none()
    
    if not winner:
        await callback.answer("❌ Нет активных пользователей с рейтингом > 10.", show_alert=True)
        return

    giveaway_bonus = 100
    winner.current_rating += giveaway_bonus
    winner.lifetime_rating += giveaway_bonus
    await db_session.commit()

    chats_result = await db_session.execute(select(ChatConfig).where(ChatConfig.is_active == True))
    active_chats = chats_result.scalars().all()
    winner_mention = f"@{winner.username}" if winner.username else winner.full_name

    for chat in active_chats:
        try:
            await callback.bot.send_message(
                chat_id=chat.id,
                text=f"🎉 **ЕЖЕДНЕВНЫЙ РОЗЫГРЫШ ЗАВЕРШЕН!** 🎉\n\n"
                     f"👑 Генератор случайных чисел выбрал победителя среди активных участников!\n"
                     f"Победитель: **{winner_mention}**\n\n"
                     f"🎁 Награда: +{giveaway_bonus} {settings.CURRENCY_NAME} на баланс! Поздравляем! 👏",
                parse_mode="Markdown"
            )
        except Exception: pass

    await callback.answer(f"🎉 Розыгрыш проведен! Победитель: {winner.full_name}", show_alert=True)

# --- FSM СЦЕНАРИЙ: ДОБАВЛЕНИЕ НАГРАДЫ ---

@router.callback_query(F.data == "act_add_reward")
async def process_add_reward_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerActivitySetup.waiting_for_reward_type)
    await callback.message.answer("📦 **Настройка сундука [Шаг 1/3]**\n\nВыбери тип создаваемой награды:", reply_markup=get_reward_type_keyboard())
    await callback.answer()
    
@router.callback_query(ManagerActivitySetup.waiting_for_reward_type, F.data.startswith("act_type:"))
async def process_reward_type_choice(callback: CallbackQuery, state: FSMContext):
    chosen_type = callback.data.split(":")[1]
    await state.update_data(reward_type=chosen_type)

    
    prompt = (
        "💎 Введите **количество рейтинга**, которое получит юзер (целое число):"
        if chosen_type == "rating" else
        "🎒 Введите **название физического товара/мерча** (например: _Худи с логотипом_):"
    )
    await callback.message.answer(f"📦 **Настройка сундука [Шаг 2/3]**\n\n{prompt}")
    await callback.answer()

@router.message(ManagerActivitySetup.waiting_for_reward_value)
async def process_reward_value(message: Message, state: FSMContext):
    data = await state.get_data()
    r_type = data.get("reward_type")
    text_input = message.text.strip()

    if r_type == "rating" and not text_input.isdigit():
        await message.answer("❌ Ошибка! Для типа 'Валюта' введите корректное целое число:")
        return

    await state.update_data(reward_value=text_input)
    await state.set_state(ManagerActivitySetup.waiting_for_reward_weight)
    await message.answer("📈 **Настройка сундука [Шаг 3/3]**\n\nУкажите **вес (вероятность) выпадения** этой награды (например, `1.0` или `0.1`):")

@router.message(ManagerActivitySetup.waiting_for_reward_weight)
async def process_reward_weight(message: Message, state: FSMContext, db_session: AsyncSession):
    raw_weight = message.text.strip().replace(",", ".")
    try:
        weight = float(raw_weight)
        if weight <= 0: raise ValueError
    except ValueError:
        await message.answer("❌ Ошибка! Вес должен быть положительным числом. Попробуйте еще раз:")
        return

    data = await state.get_data()
    new_reward = ChestReward(reward_type=data.get("reward_type"), value=data.get("reward_value"), weight=weight)
    db_session.add(new_reward)
    await db_session.commit()
    await state.clear()
    await message.answer(f"🎉 Награда успешно добавлена в призовой пул сундука!")

@router.callback_query(F.data == "act_cancel")
async def process_act_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание награды отменено.")
    await callback.answer()

# --- КЛИК ПОЛЬЗОВАТЕЛЯ: ОТКРЫТИЕ СУНДУКА В ЧАТЕ ---

@router.callback_query(F.data == "chest_open_click")
async def process_user_open_chest(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    sys_settings = await get_sys_settings(db_session)

    if db_user.current_rating < sys_settings.chest_open_price:
        await callback.answer(f"❌ Недостаточно средств! Стоимость открытия: {sys_settings.chest_open_price} {settings.CURRENCY_NAME}.", show_alert=True)
        return

    titles = settings.parsed_titles
    user_title_id = 1
    for t in sorted(titles.values(), key=lambda x: x.min_rating, reverse=True):
        if db_user.lifetime_rating >= t.min_rating:
            user_title_id = t.id
            break

    if user_title_id < sys_settings.chest_min_title_id:
        required_info = titles.get(sys_settings.chest_min_title_id)
        required_name = required_info.name if required_info else "Продвинутый"
        await callback.answer(f"🔒 Доступ ограничен! Требуется титул от '{required_name}' и выше.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            f"🔒 **Секретный сундук успешно открыт!** 🔒\n\n👤 Счастливчик: {callback.from_user.mention_html()}\n🎉 Награда выдана в личный кабинет победителя!",
            reply_markup=None, parse_mode="HTML"
        )
    except Exception:
        await callback.answer("😢 Ой! Кто-то оказался быстрее тебя и уже забрал этот сундук!", show_alert=True)
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
        try: await callback.bot.send_message(chat_id=db_user.tg_id, text=f"🎁 Твой выигрыш: +{base_rating} {settings.CURRENCY_NAME} (Утешительный приз).")
        except Exception: pass
        return

    population = [r for r in rewards]
    weights = [r.weight for r in rewards]
    win_reward = random.choices(population, weights=weights, k=1)[0]

    if win_reward.reward_type == "rating":
        amount = int(win_reward.value)
        db_user.current_rating += amount
        db_user.lifetime_rating += amount
        await db_session.commit()
        try: await callback.bot.send_message(chat_id=db_user.tg_id, text=f"🎁 Твой выигрыш: +{amount} {settings.CURRENCY_NAME} на баланс!")
        except Exception: pass
    else:
        new_order = Order(
            user_id=db_user.tg_id, source="chest", item_name=f"[СУНДУК] {win_reward.value}",
            status=OrderStatus.CREATED, delivery_data="Выиграно в сундуке чата. Укажите контакты в '🎁 Мои Награды'."
        )
        db_session.add(new_order)
        await db_session.commit()
        
        try:
            await callback.bot.send_message(
                chat_id=db_user.tg_id,
                text=f"📦 **Ура! Вы выиграли мерч:** *{win_reward.value}*\nЗаявка отправлена менеджерам, отслеживайте статус в '🎁 Мои Награды'.",
                parse_mode="Markdown"
            )
        except Exception: pass

        for manager_id in settings.managers_list:
            try:
                await callback.bot.send_message(
                    chat_id=manager_id,
                    text=f"📥 **Сундук чата:** @{db_user.username or db_user.tg_id} выиграл мерч *{win_reward.value}*.",
                    parse_mode="Markdown"
                )
            except Exception: pass

    await callback.answer()
