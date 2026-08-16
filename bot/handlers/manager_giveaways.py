import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import Giveaway, GiveawayParticipant, User, ChatConfig, ShopItem, Inventory
from bot.keyboards.manager_giveaways_kb import (
    get_giveaways_main_keyboard,
    get_ga_reward_type_keyboard,
    get_ga_condition_type_keyboard,
    get_ga_tickets_keyboard
)
from bot.keyboards.manager_activities_kb import get_titles_choice_keyboard
from bot.states import ManagerGiveawaySetup

router = Router(name="manager_giveaways_router")

async def refresh_giveaways_panel(callback_or_message, session: AsyncSession):
    """Обновляет состояние панели розыгрышей."""
    # Ищем текущий активный розыгрыш
    ga_q = select(Giveaway).where(Giveaway.is_active == True)
    active_ga = (await session.execute(ga_q)).scalar_one_or_none()

    if active_ga:
        # Считаем количество участников
        p_count_q = select(func.count(GiveawayParticipant.id)).where(GiveawayParticipant.giveaway_id == active_ga.id)
        total_participants = (await session.execute(p_count_q)).scalar()
        
        cond_str = ""
        if active_ga.condition_type == "title":
            cond_str = f"Титул от ID {active_ga.condition_value}+"
        else:
            ticket_item = await session.get(ShopItem, active_ga.condition_value)
            cond_str = f"Наличие билета '{ticket_item.name if ticket_item else 'Удален'}'"

        text = (
            "🎉 **Управление активными розыгрышами**\n\n"
            "🟢 **Сейчас запущен один активный розыгрыш:**\n"
            f"▪️ **Приз:** {active_ga.reward_value} ({'💎 Рейтинг' if active_ga.reward_type == 'rating' else '🎒 Мерч'})\n"
            f"▪️ **Призовых мест:** {active_ga.winners_count}\n"
            f"▪️ **Условие участия:** {cond_str}\n"
            f"👥 **Заявлено участников:** {total_participants} чел.\n\n"
            "Вы можете в любой момент закрыть розыгрыш и объявить случайных победителей в чатах!"
        )
    else:
        text = (
            "🎉 **Управление розыгрышами**\n\n"
            "❌ Активных лотерей сейчас нет.\n\n"
            "Вы можете создать новый кастомный розыгрыш, задать условия участия, "
            "количество призовых мест, и бот опубликует форму сбора участников."
        )

    reply_markup = get_giveaways_main_keyboard(has_active=bool(active_ga))

    if isinstance(callback_or_message, CallbackQuery):
        try: await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception: await callback_or_message.answer()
    else:
        await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")


@router.callback_query(F.data == "mg_giveaways_panel")
async def cmd_giveaways_panel_click(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await refresh_giveaways_panel(callback, db_session)
    await callback.answer()


@router.callback_query(F.data == "ga_finalize")
async def process_ga_finalize(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    ga_q = select(Giveaway).where(Giveaway.is_active == True)
    active_ga = (await db_session.execute(ga_q)).scalar_one_or_none()
    
    if not active_ga:
        await callback.answer("❌ Активный розыгрыш не найден.", show_alert=True)
        return

    # Запрашиваем всех участников лотереи
    p_q = select(GiveawayParticipant.user_id).where(GiveawayParticipant.giveaway_id == active_ga.id)
    participants_ids = (await db_session.execute(p_q)).scalars().all()

    if not participants_ids:
        active_ga.is_active = False
        await db_session.commit()
        await callback.answer("⚠️ Розыгрыш закрыт, но участников не было. Победители не определены.", show_alert=True)
        await refresh_giveaways_panel(callback, db_session)
        return

    # Защита: если участников меньше, чем призовых мест
    actual_winners_count = min(len(participants_ids), active_ga.winners_count)
    winners_ids = random.sample(participants_ids, k=actual_winners_count)

    winners_mentions = []
    for w_id in winners_ids:
        w_user = await db_session.get(User, w_id)
        if w_user:
            # Начисляем рейтинг автоматически, если приз — валюта
            if active_ga.reward_type == "rating":
                amount = int(active_ga.reward_value)
                w_user.current_rating += amount
                w_user.lifetime_rating += amount
            
            winners_mentions.append(f"👤 @{w_user.username}" if w_user.username else f"👤 {w_user.full_name}")

    # Закрываем розыгрыш
    active_ga.is_active = False
    await db_session.commit()

    # Публикуем итоги во все группы проекта
    chats_result = await db_session.execute(select(ChatConfig).where(ChatConfig.is_active == True))
    active_chats = chats_result.scalars().all()

    winners_str = "\n".join(winners_mentions)
    text_to_chats = (
        "🎉 **РОЗЫГРЫШ ЗАВЕРШЕН! ИТОГИ:** 🎉\n\n"
        f"🎁 **Разыгранный приз:** {active_ga.reward_value}\n"
        f"🏆 **Список случайных счастливчиков:**\n{winners_str}\n\n"
        "Поздравляем победителей! Награды выданы в ваши личные кабинеты! 👏"
    )

    for chat in active_chats:
        try: await callback.bot.send_message(chat_id=chat.id, text=text_to_chats, parse_mode="Markdown")
        except Exception: pass

    await callback.answer("🎉 Итоги розыгрыша успешно подведены и опубликованы!", show_alert=True)
    await refresh_giveaways_panel(callback, db_session)

# --- FSM СЦЕНАРИЙ: СОЗДАНИЕ НОВОГО РОЗЫГРЫША ---

@router.callback_query(F.data == "ga_create")
async def process_ga_create_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerGiveawaySetup.waiting_for_reward_type)
    await callback.message.answer("🎉 **Конструктор розыгрышей [Шаг 1/5]**\n\nВыбери тип главного приза:", reply_markup=get_ga_reward_type_keyboard())
    await callback.answer()


@router.callback_query(ManagerGiveawaySetup.waiting_for_reward_type, F.data.startswith("ga_type:"))
async def process_ga_reward_type(callback: CallbackQuery, state: FSMContext):
    chosen_type = callback.data.split(":")[1]
    await state.update_data(ga_reward_type=chosen_type)
    await state.set_state(ManagerGiveawaySetup.waiting_for_reward_value)
    
    prompt = (
        "💎 Введите **количество рейтинга**, которое получит каждый победитель (целое число):"
        if chosen_type == "rating" else
        "🎒 Введите **название физического приза/мерча** (например: _Игровая клавиатура_):"
    )
    await callback.message.answer(f"🎉 **Конструктор розыгрышей [Шаг 2/5]**\n\n{prompt}")
    await callback.answer()


@router.message(ManagerGiveawaySetup.waiting_for_reward_value)
async def process_ga_reward_value(message: Message, state: FSMContext):
    data = await state.get_data()
    r_type = data.get("ga_reward_type")
    text_input = message.text.strip()

    if r_type == "rating" and not text_input.isdigit():
        await message.answer("❌ Ошибка! Для типа 'Валюта' введите корректное целое число:")
        return

    await state.update_data(ga_reward_value=text_input)
    await state.set_state(ManagerGiveawaySetup.waiting_for_winners_count)
    await message.answer("👥 **Конструктор розыгрышей [Шаг 3/5]**\n\nУкажите **количество призовых мест** (сколько будет победителей, например `3`):")


@router.message(ManagerGiveawaySetup.waiting_for_winners_count)
async def process_ga_winners_count(message: Message, state: FSMContext):
    text_input = message.text.strip()
    if not text_input.isdigit() or int(text_input) <= 0:
        await message.answer("❌ Ошибка! Введите целое положительное число мест:")
        return

    await state.update_data(ga_winners_count=int(text_input))
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_type)
    await message.answer("🔒 **Конструктор розыгрышей [Шаг 4/5]**\n\nВыберите **условие входа** для участников:", reply_markup=get_ga_condition_type_keyboard())


@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_type, F.data.startswith("ga_cond:"))
async def process_ga_condition_type(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    chosen_cond = callback.data.split(":")[1]
    await state.update_data(ga_condition_type=chosen_cond)
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_value)

    if chosen_cond == "title":
        # Используем готовую клавиатуру званий из модуля сундуков
        await callback.message.answer(
            "🎖️ **Конструктор розыгрышей [Шаг 5/5]**\n\nВыберите минимальный титул для участия:",
            reply_markup=get_titles_choice_keyboard(settings.parsed_titles)
        )
    else:
        # Извлекаем из базы только те товары, которые созданы как лотерейные билеты
        tickets_q = select(ShopItem).where(and_(ShopItem.is_ticket == True, ShopItem.is_deleted == False))
        tickets = (await db_session.execute(tickets_q)).scalars().all()
        
        if not tickets:
            await callback.answer("❌ В магазине нет созданных лотерейных билетов! Сначала добавьте их в панель настроек магазина.", show_alert=True)
            await state.clear()
            await refresh_giveaways_panel(callback, db_session)
            return
            
        await callback.message.answer(
            "🎟️ **Конструктор розыгрышей [Шаг 5/5]**\n\nВыберите билет, который должен быть в инвентаре пользователя:",
            reply_markup=get_ga_tickets_keyboard(tickets)
        )
    await callback.answer()


# Финал настройки по ТИТУЛУ (использует колбэк от сундуков, так как клавиатура общая)
@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_value, F.data.startswith("act_save_title:"))
async def process_ga_finalize_title(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    title_id = int(callback.data.split(":")[1])
    await save_and_publish_giveaway(callback, state, db_session, cond_value=title_id)


# Финал настройки по БИЛЕТУ
@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_value, F.data.startswith("ga_save_cond_ticket:"))
async def process_ga_finalize_ticket(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    ticket_id = int(callback.data.split(":")[1])
    await save_and_publish_giveaway(callback, state, db_session, cond_value=ticket_id)


async def save_and_publish_giveaway(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession, cond_value: int):
    """Сборка розыгрыша, запись в БД и публикация анонса во все чаты."""
    data = await state.get_data()
    
    new_ga = Giveaway(
        reward_type=data.get("ga_reward_type"),
        reward_value=data.get("ga_reward_value"),
        winners_count=data.get("ga_winners_count"),
        condition_type=data.get("ga_condition_type"),
        condition_value=cond_value,
        is_active=True
    )
    db_session.add(new_ga)
    await db_session.commit()
    await state.clear()

    # Формируем красивый анонс для групп
    cond_text = ""
    if new_ga.condition_type == "title":
        t_name = settings.parsed_titles.get(cond_value).name
        cond_text = f"🎖️ Наличие титула от **'{t_name}'** и выше."
    else:
        ticket_item = await db_session.get(ShopItem, cond_value)
        cond_text = f"🎟️ Наличие билета **'{ticket_item.name if ticket_item else 'Билет'}'** в инвентаре."

    # Публикуем форму сбора заявок во все активные группы
    chats_result = await db_session.execute(select(ChatConfig).where(ChatConfig.is_active == True))
    active_chats = chats_result.scalars().all()

    join_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎉 Участвовать в розыгрыше!", callback_data=f"ga_join_click:{new_ga.id}")]
    ])

    text_to_chats = (
        "🎉 **ВНИМАНИЕ! ЗАПУЩЕН НОВЫЙ РОЗЫГРЫШ!** 🎉\n\n"
        f"🎁 **Главный приз:** {new_ga.reward_value}\n"
        f"🏆 **Призовых мест:** {new_ga.winners_count}\n"
        f"🔒 **Условие входа:** {cond_text}\n\n"
        "Успей заявить своё участие, кликнув по экранной кнопке ниже! 👇"
    )

    for chat in active_chats:
        try: await callback.bot.send_message(chat_id=chat.id, text=text_to_chats, reply_markup=join_kb, parse_mode="Markdown")
        except Exception: pass

    await callback.answer("🎉 Розыгрыш успешно запущен и разослан по группам!", show_alert=True)
    await refresh_giveaways_panel(callback, db_session)


@router.callback_query(F.data == "ga_cancel")
async def process_ga_cancel(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    await state.clear()
    await callback.answer("❌ Создание лотереи отменено.")
    await refresh_giveaways_panel(callback, db_session)
