import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import settings
from database.models import ChestReward, ChatConfig, User, Order, OrderStatus
from bot.keyboards.manager_activities_kb import get_activities_main_keyboard, get_reward_type_keyboard
from bot.states import ManagerActivitySetup

router = Router(name="manager_activities_router")

@router.message(F.text == "🎁 Настройка Сундука / Розыгрышей")
async def cmd_manager_activities(message: Message, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    # Считаем текущее количество наград в пуле сундука
    count_q = select(func.count(ChestReward.id))
    total_rewards = (await db_session.execute(count_q)).scalar()

    text = (
        "🎁 **Управление игровыми механиками чата**\n\n"
        "Здесь вы можете моментально активировать интерактив в подключенных группах "
        "или настроить призовой пул для секретного сундука.\n\n"
        f"📦 Всего уникальных наград в сундуке: **{total_rewards}**\n"
        "_(Если пул наград пуст, сундук будет выдавать только базовый утешительный рейтинг)_"
    )
    await message.answer(text, reply_markup=get_activities_main_keyboard(), parse_mode="Markdown")

@router.types.CallbackQuery(F.data == "act_clear_rewards")
async def process_clear_rewards(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    # Удаляем все награды из пула
    from sqlalchemy import delete
    await db_session.execute(delete(ChestReward))
    await db_session.commit()
    
    await callback.answer("✅ Призовой пул сундука полностью очищен!", show_alert=True)
    # Обновляем текст, имитируя ввод команды заново
    await cmd_manager_activities(callback.message, is_manager, db_session)
    try: await callback.message.delete()
    except Exception: pass

# --- МЕХАНИКА: ПРИНУДИТЕЛЬНЫЙ СУНДУК ---
@router.types.CallbackQuery(F.data == "act_send_chest")
async def process_send_chest_now(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    # Ищем все чаты, где разрешена активность
    chats_result = await db_session.execute(select(ChatConfig).where(ChatConfig.is_active == True))
    active_chats = chats_result.scalars().all()
    
    if not active_chats:
        await callback.answer("❌ Нет подключенных активных чатов для отправки сундука!", show_alert=True)
        return

    sent_count = 0
    # Создаем интерактивную инлайн-кнопку для пользователей чата
    chest_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Открыть сундук!", callback_data="chest_open_click")]
    ])

    for chat in active_chats:
        try:
            await callback.bot.send_message(
                chat_id=chat.id,
                text=f"📦 **ВНИМАНИЕ! В ЧАТЕ ПОЯВИЛСЯ СЕКРЕТНЫЙ СУНДУК!** 📦\n\n"
                     f"Кто первый нажмет на кнопку ниже, тот и заберет случайную награду! Погнали! 👇",
                reply_markup=chest_kb,
                parse_mode="Markdown"
            )
            sent_count += 1
        except Exception:
            pass # Если бота кикнули из группы, пропускаем

    await callback.answer(f"🚀 Сундук успешно заброшен в {sent_count} чат(ов)!", show_alert=True)

# --- МЕХАНИКА: МГНОВЕННЫЙ РОЗЫГРЫШ СРЕДИ АКТИВНЫХ ---
@router.types.CallbackQuery(F.data == "act_run_giveaway")
async def process_run_giveaway(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    # Случайным образом выбираем пользователя, у которого lifetime_rating > 10 (чтобы отсечь мертвые аккаунты)
    # И который не является ботом/менеджером
    query = select(User).where(User.lifetime_rating > 10).order_by(func.random()).limit(1)
    result = await db_session.execute(query)
    winner = result.scalar_one_or_none()
    
    if not winner:
        await callback.answer("❌ Недостаточно активных пользователей в базе данных для проведения розыгрыша.", show_alert=True)
        return

    # Начисляем победителю праздничный бонус
    giveaway_bonus = 100
    winner.current_rating += giveaway_bonus
    winner.lifetime_rating += giveaway_bonus
    await db_session.commit()

    # Оповещаем во все чаты
    chats_result = await db_session.execute(select(ChatConfig).where(ChatConfig.is_active == True))
    active_chats = chats_result.scalars().all()
    
    winner_mention = f"@{winner.username}" if winner.username else winner.full_name

    for chat in active_chats:
        try:
            await callback.bot.send_message(
                chat_id=chat.id,
                text=f"🎉 **ЕЖЕДНЕВНЫЙ СУПЕР-РОЗЫГРЫШ ЗАВЕРШЕН!** 🎉\n\n"
                     f"👑 Случайный генератор выбрал самого активного участника сообщества!\n"
                     f"Победитель: **{winner_mention}**\n\n"
                     f"🎁 Награда: +{giveaway_bonus} {settings.CURRENCY_NAME} на баланс! Поздравляем! 👏",
                parse_mode="Markdown"
            )
        except Exception: pass

    await callback.answer(f"🎉 Розыгрыш проведен! Победитель: {winner.full_name}", show_alert=True)

# --- FSM СЦЕНАРИЙ: ДОБАВЛЕНИЕ НАГРАДЫ В СУНДУК ---
@router.types.CallbackQuery(F.data == "act_add_reward")
async def process_add_reward_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerActivitySetup.waiting_for_reward_type)
    
    await callback.message.answer(
        "📦 **Настройка сундука [Шаг 1/3]**\n\nВыбери тип создаваемой награды:",
        reply_markup=get_reward_type_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.types.CallbackQuery(ManagerActivitySetup.waiting_for_reward_type, F.data.startswith("act_type:"))
async def process_reward_type_choice(callback: CallbackQuery, state: FSMContext):
    chosen_type = callback.data.split(":")[1]
    await state.update_data(reward_type=chosen_type)
    await state.set_state(ManagerActivitySetup.waiting_for_reward_value)
    
    prompt = (
        "💎 Введите **количество рейтинга**, которое получит юзер (целое число, например: `150`):"
        if chosen_type == "rating" else
        "🎒 Введите **название физического товара/мерча** (например: _Худи с логотипом_):"
    )
    await callback.message.answer(f"📦 **Настройка сундука [Шаг 2/3]**\n\n{prompt}", parse_mode="Markdown")
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
    
    await message.answer(
        "📈 **Настройка сундука [Шаг 3/3]**\n\n"
        "Укажите **вес (вероятность) выпадения** этой награды относительно других.\n"
        "👉 Введите любое дробное или целое число (например, `1.0` — стандарт, `0.1` — редкая награда, `5.0` — частая награда):",
        parse_mode="Markdown"
    )

@router.message(ManagerActivitySetup.waiting_for_reward_weight)
async def process_reward_weight(message: Message, state: FSMContext, db_session: AsyncSession):
    raw_weight = message.text.strip().replace(",", ".")
    try:
        weight = float(raw_weight)
        if weight <= 0: raise ValueError
    except ValueError:
        await message.answer("❌ Ошибка! Вес должен быть положительным числом (например, 1.0 или 0.5). Попробуйте еще раз:")
        return

    data = await state.get_data()
    
    new_reward = ChestReward(
        reward_type=data.get("reward_type"),
        value=data.get("reward_value"),
        weight=weight
    )
    db_session.add(new_reward)
    await db_session.commit()
    await state.clear()

    await message.answer(f"🎉 Награда **{new_reward.value}** (тип: {new_reward.reward_type}) успешно добавления в призовой пул сундука!")

@router.types.CallbackQuery(F.data == "act_cancel")
async def process_act_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание награды отменено.")
    await callback.answer()
