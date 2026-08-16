import random
from datetime import datetime
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
    get_ga_tickets_keyboard,
    get_ga_titles_choice_keyboard
)
from bot.states import ManagerGiveawaySetup

router = Router(name="manager_giveaways_router")

async def refresh_giveaways_panel(callback_or_message, session: AsyncSession):
    """Обновляет состояние экранной панели розыгрышей с выводом расписания."""
    ga_q = select(Giveaway).where(Giveaway.status.in_(["created", "announced"])).order_by(Giveaway.id.desc())
    active_ga = (await session.execute(ga_q)).scalar_one_or_none()

    if active_ga:
        parts = str(active_ga.condition_value).split(":")
        title_id = int(parts[0])
        ticket_id = int(parts[1])
        
        t_name = settings.parsed_titles.get(title_id).name
        
        # Адаптивный вывод условий в панели
        if ticket_id == 0:
            cond_str = f"🎖️ Титул от '{t_name}' и выше (Вход БЕСПЛАТНЫЙ, без билетов)"
        else:
            ticket_item = await session.get(ShopItem, ticket_id)
            cond_str = f"🎖️ Титул от '{t_name}' + 🎟️ Билет '{ticket_item.name if ticket_item else 'Удален'}'"

        status_labels = {
            "created": "⏳ Ожидает анонса",
            "announced": "🟢 Анонсирован / Сбор участников"
        }

        text = (
            "🎉 **Управление автоматическими розыгрышами**\n\n"
            "📋 **Текущий запланированный ивент:**\n"
            f"▪️ **Статус:** {status_labels.get(active_ga.status)}\n"
            f"▪️ **Приз:** {active_ga.reward_value} ({'💎 Рейтинг' if active_ga.reward_type == 'rating' else '🎒 Мерч'})\n"
            f"▪️ **Призовых мест:** {active_ga.winners_count}\n"
            f"📢 **Время анонса:** `{active_ga.announce_at.strftime('%d.%m.%Y %H:%M')}`\n"
            f"🛑 **Время финала:** `{active_ga.finalize_at.strftime('%d.%m.%Y %H:%M')}`\n\n"
            f"🔒 **Критерий отбора:** {cond_str}\n\n"
            "ℹ️ _Бот сам опубликует анонс и подведет итоги в чатах по расписанию через воркер!_"
        )
    else:
        text = (
            "🎉 **Управление розыгрышами**\n\n"
            "❌ Запланированных автоматических лотерей сейчас нет.\n\n"
            "Вы можете создать новый розыгрыш, задав точное время анонса требований "
            "и время финала. Бот всё сделает за вас!"
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

# --- FSM СЦЕНАРИЙ: НАСТРОЙКА КРИТЕРИЕВ РОЗЫГРЫША ---

@router.callback_query(F.data == "ga_create")
async def process_ga_create_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerGiveawaySetup.waiting_for_reward_type)
    await callback.message.answer("🎉 **Конструктор розыгрышей [Шаг 1/7]**\n\nВыбери тип приза лотереи:", reply_markup=get_ga_reward_type_keyboard())
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
    await callback.message.answer(f"🎉 **Конструктор розыгрышей [Шаг 2/7]**\n\n{prompt}")
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
    await message.answer("👥 **Конструктор розыгрышей [Шаг 3/7]**\n\nУкажите **количество призовых мест** (сколько будет победителей):")


@router.message(ManagerGiveawaySetup.waiting_for_winners_count)
async def process_ga_winners_count(message: Message, state: FSMContext):
    text_input = message.text.strip()
    if not text_input.isdigit() or int(text_input) <= 0:
        await message.answer("❌ Ошибка! Введите целое положительное число мест:")
        return

    await state.update_data(ga_winners_count=int(text_input))
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_type)
    
    await message.answer(
        "🎖️ **Конструктор розыгрышей [Шаг 4/7]**\n\n"
        "Задайте **минимальный титул**, которым должен обладать пользователь для участия:",
        reply_markup=get_ga_titles_choice_keyboard(settings.parsed_titles)
    )


@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_type, F.data.startswith("ga_save_title:"))
async def process_ga_condition_title_chosen(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    title_id = int(callback.data.split(":")[1])
    await state.update_data(ga_cond_title_id=title_id)
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_value)
    
    tickets_q = select(ShopItem).where(and_(ShopItem.is_ticket == True, ShopItem.is_deleted == False))
    tickets = (await db_session.execute(tickets_q)).scalars().all()
    
    # Модифицируем клавиатуру билетов: добавляем кнопку «Пропустить»
    kb_buttons = []
    for t in tickets:
        kb_buttons.append([InlineKeyboardButton(text=f"🎟️ {t.name}", callback_data=f"ga_save_cond_ticket:{t.id}")])
    
    # КНОПКА СПАСЕНИЯ: Розыгрыш без билета
    kb_buttons.append([InlineKeyboardButton(text="⏩ Пропустить билет (Только по Титулу)", callback_data="ga_save_cond_ticket:0")])
    kb_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ga_cancel")])
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
    await callback.message.edit_text(
        "🎟️ **Конструктор розыгрышей [Шаг 5/7]**\n\n"
        "Выберите **билет**, наличие которого бот проверит в инвентаре участников.\n\n"
        "👉 _Если вы хотите провести открытый розыгрыш для всех участников с выбранным титулом, нажмите кнопку ниже:_ ",
        reply_markup=reply_markup
    )
    await callback.answer()

# --- FSM СЦЕНАРИЙ: НАСТРОЙКА ВРЕМЕНИ И СОХРАНЕНИЕ ---

@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_value, F.data.startswith("ga_save_cond_ticket:"))
async def process_ga_condition_ticket_chosen(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split(":"))
    await state.update_data(ga_cond_ticket_id=ticket_id)
    
    await state.set_state(ManagerGiveawaySetup.waiting_for_announce_time)
    await callback.message.edit_text(
        "📢 **Конструктор розыгрышей [Шаг 6/7]**\n\n"
        "Введите дату и время **публикации анонса** в чатах.\n"
        "Формат строго: `ДД.ММ.ГГГГ ЧЧ:ММ` (например, `17.08.2026 15:00`):"
    )
    await callback.answer()


@router.message(ManagerGiveawaySetup.waiting_for_announce_time)
async def process_ga_announce_time(message: Message, state: FSMContext):
    text_input = message.text.strip()
    try:
        dt_announce = datetime.strptime(text_input, "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Ошибка! Неверный формат даты. Введите строго по шаблону `ДД.ММ.ГГГГ ЧЧ:ММ`:")
        return

    await state.update_data(ga_time_announce=dt_announce)
    await state.set_state(ManagerGiveawaySetup.waiting_for_finalize_time)
    await message.answer(
        "🛑 **Конструктор розыгрышей [Шаг 7/7]**\n\n"
        "Введите дату и время **автоматического финала** лотереи.\n"
        "Формат строго: `ДД.ММ.ГГГГ ЧЧ:ММ` (например, `18.08.2026 21:00`):"
    )


@router.message(ManagerGiveawaySetup.waiting_for_finalize_time)
async def process_ga_finalize_time_and_save(message: Message, state: FSMContext, db_session: AsyncSession):
    text_input = message.text.strip()
    try:
        dt_finalize = datetime.strptime(text_input, "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Ошибка! Неверный формат даты. Введите строго по шаблону `ДД.ММ.ГГГГ ЧЧ:ММ`:")
        return

    data = await state.get_data()
    dt_announce = data.get("ga_time_announce")

    if dt_finalize <= dt_announce:
        await message.answer("❌ Ошибка! Время финала не может быть раньше или равно времени анонса. Попробуйте еще раз:")
        return

    title_id = data.get("ga_cond_title_id")
    ticket_id = data.get("ga_cond_ticket_id")
    combo_value = f"{title_id}:{ticket_id}"

    new_ga = Giveaway(
        reward_type=data.get("ga_reward_type"),
        reward_value=data.get("ga_reward_value"),
        winners_count=data.get("ga_winners_count"),
        condition_type="combo",
        condition_value=combo_value,
        announce_at=dt_announce,
        finalize_at=dt_finalize,
        status="created"
    )
    db_session.add(new_ga)
    await db_session.commit()
    await state.clear()

    # Сборка анонса для вывода менеджеру
    t_name = settings.parsed_titles.get(title_id).name
    if ticket_id == 0:
        cond_text = f"🎖️ Наличие титула от **'{t_name}'** и выше (Участие открытое, без билетов)."
    else:
        ticket_item = await db_session.get(ShopItem, ticket_id)
        ticket_name = ticket_item.name if ticket_item else "Билет"
        cond_text = f"🎖️ Титул от **'{t_name}'** + 🎟️ Билет **'{ticket_name}'** в инвентаре."

    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await message.answer(
        f"🎉 **Автоматический розыгрыш успешно запланирован!**\n\n"
        f"🔒 **Критерий:** {cond_text}\n"
        f"📢 **Анонс:** {dt_announce.strftime('%d.%m.%Y %H:%M')}\n"
        f"🛑 **Финал:** {dt_finalize.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Бот сам опубликует требования в чаты и подведет итоги через APScheduler.",
        reply_markup=get_back_to_menu_keyboard(to_manager=True)
    )
    await refresh_giveaways_panel(message, db_session)


@router.callback_query(F.data == "ga_cancel")
async def process_ga_cancel(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    await state.clear()
    await callback.answer("❌ Создание розыгрыша отменено.")
    await refresh_giveaways_panel(callback, db_session)
