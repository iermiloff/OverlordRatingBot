import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import Giveaway, User, ChatConfig, ShopItem, Inventory
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
    """Обновляет состояние экранной панели розыгрышей менеджера."""
    ga_q = select(Giveaway).where(Giveaway.is_active == True)
    active_ga = (await session.execute(ga_q)).scalar_one_or_none()

    if active_ga:
        # Извлекаем данные для красивого отображения комбинированных условий
        parts = str(active_ga.condition_value).split(":")
        title_id = int(parts[0])
        ticket_id = int(parts[1])
        
        t_name = settings.parsed_titles.get(title_id).name
        ticket_item = await session.get(ShopItem, ticket_id)
        ticket_name = ticket_item.name if ticket_item else "Удален"

        text = (
            "🎉 **Управление автоматическими розыгрышами**\n\n"
            "🟢 **Сейчас запущен один активный ивент:**\n"
            f"▪️ **Приз:** {active_ga.reward_value} ({'💎 Рейтинг' if active_ga.reward_type == 'rating' else '🎒 Мерч'})\n"
            f"▪️ **Призовых мест:** {active_ga.winners_count}\n"
            f"🔒 **КОМБИНИРОВАННОЕ УСЛОВИЕ ВХОДА (АНТИБОТ):**\n"
            f"   1. 🎖️ Титул от **'{t_name}'** и выше\n"
            f"   2. 🎟️ Билет **'{ticket_name}'** в инвентаре\n\n"
            "🔥 **Математика шансов:** Каждый купленный билет увеличивает вероятность победы! "
            "Бот сам просчитает веса участников и объявит итоги при закрытии лотереи."
        )
    else:
        text = (
            "🎉 **Управление розыгрышами**\n\n"
            "❌ Активных автоматических лотерей сейчас нет.\n\n"
            "Вы можете создать новый комбинированный розыгрыш, задав обязательный титул "
            "и лотерейный билет. Каждый билет в инвентаре китов будет пропорционально умножать их шансы!"
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

    # Депарсим составное условие condition_value -> "title_id:ticket_id"
    parts = str(active_ga.condition_value).split(":")
    title_id = int(parts[0])
    ticket_id = int(parts[1])

    target_title_info = settings.parsed_titles.get(title_id)
    min_rating_required = target_title_info.min_rating if target_title_info else 0

    # 1. ЖЕСТКИЙ СИНХРОННЫЙ ФИЛЬТР: ТИТУЛ И БИЛЕТ ОДНОВРЕМЕННО
    users_q = (
        select(User, Inventory.quantity)
        .join(Inventory, Inventory.user_id == User.tg_id)
        .where(and_(
            User.lifetime_rating >= min_rating_required,
            Inventory.item_id == ticket_id,
            Inventory.quantity >= 1,
            User.is_banned == False
        ))
    )
    query_result = await db_session.execute(users_q)
    eligible_records = query_result.all()  # Получаем список кортежей (User, quantity)

    if not eligible_records:
        active_ga.is_active = False
        await db_session.commit()
        await callback.answer("⚠️ Розыгрыш закрыт. Ни один пользователь не подошел под критерии (Титул + Билет).", show_alert=True)
        await refresh_giveaways_panel(callback, db_session)
        return

    # 2. ПОСТРОЕНИЕ ЛОТЕРЕЙНОГО БАРАБАНА (ПРОПОРЦИОНАЛЬНОЕ УМНОЖЕНИЕ ШАНСОВ)
    lottery_wheel = []
    user_ticket_map = {}  # Кэш количества билетов, чтобы не делать повторные селекты

    for user_obj, ticket_qty in eligible_records:
        user_ticket_map[user_obj.tg_id] = ticket_qty
        # Добавляем пользователя в барабан столько раз, сколько у него билетов на руках
        for _ in range(ticket_qty):
            lottery_wheel.append(user_obj)

    # Вычисляем уникальных победителей
    winners = []
    actual_winners_count = min(len(eligible_records), active_ga.winners_count)

    while len(winners) < actual_winners_count and lottery_wheel:
        chosen_one = random.choice(lottery_wheel)
        if chosen_one not in winners:
            winners.append(chosen_one)
        # Удаляем все его купоны из текущего колеса, чтобы один юзер не занял два места в одном ивенте
        lottery_wheel = [u for u in lottery_wheel if u.tg_id != chosen_one.tg_id]

    winners_mentions = []
    
    # 3. НАЧИСЛЕНИЕ ПРИЗОВ И УТИЛИЗАЦИЯ (СПИСАНИЕ БИЛЕТОВ)
    for winner in winners:
        # Списываем строго 1 билет за участие/победу
        inv_q = select(Inventory).where(and_(Inventory.user_id == winner.tg_id, Inventory.item_id == ticket_id))
        user_ticket = (await db_session.execute(inv_q)).scalar_one_or_none()
        if user_ticket:
            user_ticket.quantity -= 1

        # Начисляем награду
        if active_ga.reward_type == "rating":
            amount = int(active_ga.reward_value)
            winner.current_rating += amount
            winner.lifetime_rating += amount
            
        total_tickets_user = user_ticket_map.get(winner.tg_id, 1)
        winners_mentions.append(
            f"👑 @{winner.username or winner.full_name} — _выиграл купон из {total_tickets_user} билетов!_"
        )

    active_ga.is_active = False
    await db_session.commit()

    # Рассылка итогов в чаты
    chats_result = await db_session.execute(select(ChatConfig).where(ChatConfig.is_active == True))
    active_chats = chats_result.scalars().all()

    winners_str = "\n".join(winners_mentions)
    text_to_chats = (
        "🎉 **МЕГА-РОЗЫГРЫШ ЗАВЕРШЕН! ИТОГИ:** 🎉\n\n"
        "Бот просканировал базу данных чата, отфильтровал ботов по званиям и билетам, "
        "а затем распределил победные места с учетом веса (количества) билетов участников! 🔥\n\n"
        f"🎁 **Разыгранный приз:** {active_ga.reward_value}\n"
        f"🏆 **Наши счастливые победители:**\n{winners_str}\n\n"
        "Поздравляем! Награды выданы, а счастливые билеты успешно погашены! Увидимся в следующих ивентах! 👏"
    )

    for chat in active_chats:
        try: await callback.bot.send_message(chat_id=chat.id, text=text_to_chats, parse_mode="Markdown")
        except Exception: pass

    await callback.answer("🎉 Автоматический расчет завершен, итоги опубликованы!", show_alert=True)
    await refresh_giveaways_panel(callback, db_session)

# --- FSM СЦЕНАРИЙ: КОНСТРУКТОР КОМБИНИРОВАННЫХ РОЗЫГРЫШЕЙ ---

@router.callback_query(F.data == "ga_create")
async def process_ga_create_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerGiveawaySetup.waiting_for_reward_type)
    await callback.message.answer("🎉 **Конструктор розыгрышей [Шаг 1/5]**\n\nВыбери тип приза лотереи:", reply_markup=get_ga_reward_type_keyboard())
    await callback.answer()


@router.callback_query(ManagerGiveawaySetup.waiting_for_reward_type, F.data.startswith("ga_type:"))
async def process_ga_reward_type(callback: CallbackQuery, state: FSMContext):
    chosen_type = callback.data.split(":")[1]
    await state.update_data(ga_reward_type=chosen_type)
    await state.set_state(ManagerGiveawaySetup.waiting_for_reward_value)
    
    prompt = (
        "💎 Введите **количество рейтинга**, которое получит каждый победитель (целое число):"
        if chosen_type == "rating" else
        "🎒 Введите **название физического мерча** (например: _Игровая клавиатура_):"
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
    await message.answer("👥 **Конструктор розыгрышей [Шаг 3/5]**\n\nУкажите **количество призовых мест** (сколько будет победителей):")


@router.message(ManagerGiveawaySetup.waiting_for_winners_count)
async def process_ga_winners_count(message: Message, state: FSMContext):
    text_input = message.text.strip()
    if not text_input.isdigit() or int(text_input) <= 0:
        await message.answer("❌ Ошибка! Введите целое положительное число мест:")
        return

    await state.update_data(ga_winners_count=int(text_input))
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_type) # Переход к званию
    
    # ЖЕСТКАЯ СЦЕНАРНАЯ ПОСЛЕДОВАТЕЛЬНОСТЬ (АНТИФРОД УСЛОВИЕ 1)
    await message.answer(
        "🎖️ **Конструктор розыгрышей [Шаг 4/5]**\n\n"
        "Задайте **минимальный титул**, которым должен обладать пользователь для прохождения фильтра:",
        reply_markup=get_titles_choice_keyboard(settings.parsed_titles)
    )


# Ловим выбор ТИТУЛА на шаге 4
@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_type, F.data.startswith("act_save_title:"))
async def process_ga_condition_title_chosen(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    title_id = int(callback.data.split(":")[1])
    await state.update_data(ga_cond_title_id=title_id)
    
    # Переходим к шагу 5: Билет
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_value)
    
    tickets_q = select(ShopItem).where(and_(ShopItem.is_ticket == True, ShopItem.is_deleted == False))
    tickets = (await db_session.execute(tickets_q)).scalars().all()
    
    if not tickets:
        await callback.answer("❌ В магазине нет билетов! Сначала добавьте их в панель настроек магазина.", show_alert=True)
        await state.clear()
        await refresh_giveaways_panel(callback, db_session)
        return
        
    await callback.message.answer(
        "🎟️ **Конструктор розыгрышей [Шаг 5/5]**\n\n"
        "Теперь выберите **билет**, наличие которого бот проверит в инвентаре (и умножит шансы на его количество):",
        reply_markup=get_ga_tickets_keyboard(tickets)
    )
    await callback.answer()


# Финал: ловим выбор БИЛЕТА на шаге 5 и пакуем комбинированные условия в БД
@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_value, F.data.startswith("ga_save_cond_ticket:"))
async def process_ga_finalize_combo(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    ticket_id = int(callback.data.split(":")[1])
    
    data = await state.get_data()
    title_id = data.get("ga_cond_title_id")

    # Пакуем комбинированные ID в строку вида "title_id:ticket_id"
    combo_condition_value = f"{title_id}:{ticket_id}"

    new_ga = Giveaway(
        reward_type=data.get("ga_reward_type"),
        reward_value=data.get("ga_reward_value"),
        winners_count=data.get("ga_winners_count"),
        condition_type="combo",  # Маркер комбинированного антифрод-режима
        condition_value=combo_condition_value,
        is_active=True
    )
    db_session.add(new_ga)
    await db_session.commit()
    await state.clear()

    # Сборка красивого анонса лотереи для отправки во все группы активности
    t_name = settings.parsed_titles.get(title_id).name
    ticket_item = await db_session.get(ShopItem, ticket_id)
    ticket_name = ticket_item.name if ticket_item else "Лотерейный Билет"

    chats_result = await db_session.execute(select(ChatConfig).where(ChatConfig.is_active == True))
    active_chats = chats_result.scalars().all()

    text_to_chats = (
        "🎉 **ЗАПУЩЕН МЕГА-РОЗЫГРЫШ С АВТО-ОТБОРОМ УЧАСТНИКОВ!** 🎉\n\n"
        f"🎁 **Каждый победитель получит:** {new_ga.reward_value}\n"
        f"🏆 **Всего призовых мест:** {new_ga.winners_count}\n\n"
        f"🔒 **ЖЕСТКИЕ КРИТЕРИИ УЧАСТИЯ (ЗАЩИТА ОТ БОТОВ):**\n"
        f"1. 🎖️ Наличие титула от **'{t_name}'** и выше.\n"
        f"2. 🎟️ Наличие билета **'{ticket_name}'** в вашем инвентаре.\n\n"
        f"📈 **Больше билетов = Выше шанс!** Каждый билет в вашем инвентаре дублирует "
        f"ваше имя в лотерейном барабане бота. Билеты можно купить в '🛍️ Магазин товаров'.\n\n"
        "ℹ️ _Заявки отправлять не нужно! Общайтесь в чате, бот сам проверит базу при подведении итогов!_"
    )

    for chat in active_chats:
        try: await callback.bot.send_message(chat_id=chat.id, text=text_to_chats, parse_mode="Markdown")
        except Exception: pass

    await callback.answer("🎉 Автоматический комбинированный розыгрыш запущен!", show_alert=True)
    await refresh_giveaways_panel(callback, db_session)


@router.callback_query(F.data == "ga_cancel")
async def process_ga_cancel(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    await state.clear()
    await callback.answer("❌ Создание лотереи отменено.")
    await refresh_giveaways_panel(callback, db_session)
