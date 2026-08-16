import random
from datetime import datetime
import pytz  # Библиотека для работы с мировыми часовыми поясами
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

GIVEAWAYS_PER_PAGE = 3

async def send_giveaways_list_page(callback_or_message, session: AsyncSession, manager_user: User, page: int = 1):
    """Отрисовка интерактивной сетки всех запланированных розыгрышей чата."""
    count_query = select(func.count(Giveaway.id)).where(Giveaway.status.in_(["created", "announced"]))
    total_ga = (await session.execute(count_query)).scalar()

    buttons = []
    
    if total_ga == 0:
        text = (
            "🎉 **Управление сеткой розыгрышей**\n\n"
            "❌ В данный момент в календаре нет запланированных автоматических лотерей.\n\n"
            "Вы можете создать сразу несколько параллельных розыгрышей наперед!"
        )
        buttons.append([InlineKeyboardButton(text="➕ Создать новый розыгрыш", callback_data="ga_create")])
        buttons.append([InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    else:
        offset_value = (page - 1) * GIVEAWAYS_PER_PAGE
        ga_query = (
            select(Giveaway)
            .where(Giveaway.status.in_(["created", "announced"]))
            .order_by(Giveaway.announce_at.asc())
            .limit(GIVEAWAYS_PER_PAGE)
            .offset(offset_value)
        )
        giveaways = (await session.execute(ga_query)).scalars().all()
        has_next = (page * GIVEAWAYS_PER_PAGE) < total_ga

        lines = [f"🎉 **Сетка запланированных розыгрышей (Страница {page})**\n"]
        
        user_tz_str = manager_user.timezone or "UTC"
        manager_tz = pytz.timezone(user_tz_str)

        for ga in giveaways:
            local_announce = ga.announce_at.replace(tzinfo=pytz.utc).astimezone(manager_tz)
            local_finalize = ga.finalize_at.replace(tzinfo=pytz.utc).astimezone(manager_tz)
            
            # ИСПРАВЛЕНО: Явно депарсим составное условие по точным индексам массива
            parts = str(ga.condition_value).split(":")
            title_id = int(parts[0])
            ticket_id = int(parts[1])
            
            t_name = settings.parsed_titles.get(title_id).name
            cond_label = f"Титул '{t_name}'" + (f" + Билет №{ticket_id}" if ticket_id > 0 else " (Без билета)")
            
            status_label = "⏳ Ожидает" if ga.status == "created" else "📢 Анонсирован"

            lines.append(
                f"🆔 **ID:** `{ga.id}` | {status_label}\n"
                f"🎁 Приз: *{ga.reward_value}* ({ga.winners_count} мест)\n"
                f"📅 Анонс ({user_tz_str}): `{local_announce.strftime('%d.%m.%Y %H:%M')}`\n"
                f"🛑 Финал ({user_tz_str}): `{local_finalize.strftime('%d.%m.%Y %H:%M')}`\n"
                f"🔒 Условие: _{cond_label}_\n"
            )
            
            buttons.append([
                InlineKeyboardButton(text=f"🗑️ Удалить лотерею №{ga.id}", callback_data=f"ga_delete_id:{ga.id}:{page}")
            ])

        text = "\n".join(lines)
        
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"ga_list_page:{page-1}"))
        if has_next:
            nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"ga_list_page:{page+1}"))
        if nav_row:
            buttons.append(nav_row)

        buttons.append([InlineKeyboardButton(text="➕ Распланировать еще один розыгрыш", callback_data="ga_create")])
        buttons.append([InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    if isinstance(callback_or_message, CallbackQuery):
        try: await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception: await callback_or_message.answer()
    else:
        await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")


@router.callback_query(F.data == "mg_giveaways_panel")
@router.callback_query(F.data.startswith("ga_list_page:"))
async def process_giveaways_panel_and_pagination(callback: CallbackQuery, is_manager: bool, db_user: User, db_session: AsyncSession):
    if not is_manager: return
    page = 1
    if callback.data.startswith("ga_list_page:"):
        # ИСПРАВЛЕНО: берём точечный строковый элемент по индексу 1
        page = int(callback.data.split(":")[1])
    await send_giveaways_list_page(callback, db_session, db_user, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("ga_delete_id:"))
async def process_ga_delete(callback: CallbackQuery, is_manager: bool, db_user: User, db_session: AsyncSession):
    if not is_manager: return
    parts = callback.data.split(":")
    # ИСПРАВЛЕНО: расставили точные индексы элементов split для удаления
    ga_id = int(parts[1])
    page = int(parts[2])

    ga = await db_session.get(Giveaway, ga_id)
    if ga:
        await db_session.delete(ga)
        await db_session.commit()
        await callback.answer(f"✅ Розыгрыш №{ga_id} успешно аннулирован и удален из сетки расписания!", show_alert=True)
    
    await send_giveaways_list_page(callback, db_session, db_user, page=page)


# --- FSM СЦЕНАРИЙ: НАСТРОЙКА КРИТЕРИЕВ РОЗЫГРЫША ---

@router.callback_query(F.data == "ga_create")
async def process_ga_create_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerGiveawaySetup.waiting_for_reward_type)
    await callback.message.edit_text("🎉 **Конструктор розыгрышей [Шаг 1/7]**\n\nВыбери тип приза лотереи:", reply_markup=get_ga_reward_type_keyboard(), parse_mode="Markdown")
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
    await callback.message.edit_text(f"🎉 **Конструктор розыгрышей [Шаг 2/7]**\n\n{prompt}", parse_mode="Markdown")
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
    
    kb_buttons = []
    for t in tickets:
        kb_buttons.append([InlineKeyboardButton(text=f"🎟️ {t.name}", callback_data=f"ga_save_cond_ticket:{t.id}")])
    
    kb_buttons.append([InlineKeyboardButton(text="⏩ Пропустить билет (Только по Титулу)", callback_data="ga_save_cond_ticket:0")])
    kb_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="ga_cancel")])
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        
    await callback.message.edit_text(
        "🎟️ **Конструктор розыгрышей [Шаг 5/7]**\n\n"
        "Выберите **билет**, наличие которого бот проверит в инвентаре участников.\n\n"
        "👉 _Если вы хотите провести открытый розыгрыш для всех участников с выбранным титулом, нажмите кнопку ниже:_ ",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    await callback.answer()

# --- FSM СЦЕНАРИЙ: НАСТРОЙКА ВРЕМЕНИ ПО ТАЙМЗОНЕ ПРОФИЛЯ, КОНВЕРТАЦИЯ И СОХРАНЕНИЕ ---

@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_value, F.data.startswith("ga_save_cond_ticket:"))
async def process_ga_condition_ticket_chosen(callback: CallbackQuery, state: FSMContext, db_user: User):
    ticket_id = int(callback.data.split(":")[1])
    await state.update_data(ga_cond_ticket_id=ticket_id)
    
    user_tz_str = db_user.timezone or "UTC"
    await state.set_state(ManagerGiveawaySetup.waiting_for_announce_time)
    await callback.message.edit_text(
        "📢 **Конструктор розыгрышей [Шаг 6/7]**\n\n"
        "Укажите дату и время **публикации анонса** требований в чатах.\n\n"
        f"⏱️ Вводите время по вашему часовому поясу профиля: **{user_tz_str}**.\n"
        "Формат: `ДД.ММ.ГГГГ ЧЧ:ММ` (например, `17.08.2026 15:00`):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ManagerGiveawaySetup.waiting_for_announce_time)
async def process_ga_announce_time(message: Message, state: FSMContext, db_user: User):
    text_input = message.text.strip()
    user_tz_str = db_user.timezone or "UTC"
    try:
        # Локализуем введенную строку времени под часовой пояс менеджера
        manager_tz = pytz.timezone(user_tz_str)
        dt_local = datetime.strptime(text_input, "%d.%m.%Y %H:%M")
        dt_local_localized = manager_tz.localize(dt_local)
        
        # Конвертируем в чистое UTC для фонового планировщика сервера
        dt_utc_announce = dt_local_localized.astimezone(pytz.utc).replace(tzinfo=None)
    except ValueError:
        await message.answer("❌ Ошибка! Неверный формат даты. Введите строго по шаблону `ДД.ММ.ГГГГ ЧЧ:ММ`:")
        return

    await state.update_data(ga_time_announce=dt_utc_announce, ga_raw_local_announce=text_input)
    await state.set_state(ManagerGiveawaySetup.waiting_for_finalize_time)
    await message.answer(
        "🛑 **Конструктор розыгрышей [Шаг 7/7]**\n\n"
        "Укажите дату и время **автоматического подведения итогов** лотереи.\n\n"
        f"⏱️ Вводите время по вашему часовому поясу профиля: **{user_tz_str}**.\n"
        "Формат: `ДД.ММ.ГГГГ ЧЧ:ММ` (например, `18.08.2026 21:00`):"
    )


@router.message(ManagerGiveawaySetup.waiting_for_finalize_time)
async def process_ga_finalize_time_and_save(message: Message, state: FSMContext, db_user: User, db_session: AsyncSession):
    text_input = message.text.strip()
    user_tz_str = db_user.timezone or "UTC"
    try:
        manager_tz = pytz.timezone(user_tz_str)
        dt_local = datetime.strptime(text_input, "%d.%m.%Y %H:%M")
        dt_local_localized = manager_tz.localize(dt_local)
        
        dt_utc_finalize = dt_local_localized.astimezone(pytz.utc).replace(tzinfo=None)
    except ValueError:
        await message.answer("❌ Ошибка! Неверный формат даты. Введите строго по шаблону `ДД.ММ.ГГГГ ЧЧ:ММ`:")
        return

    data = await state.get_data()
    dt_utc_announce = data.get("ga_time_announce")

    if dt_utc_finalize <= dt_utc_announce:
        await message.answer("❌ Ошибка! Время финала не может быть раньше или равно времени анонса. Попробуйте еще раз:")
        return

    title_id = data.get("ga_cond_title_id")
    ticket_id = data.get("ga_cond_ticket_id")
    combo_value = f"{title_id}:{ticket_id}"

    new_ga = Giveaway(
        reward_type=data.get("ga_reward_type")[0],
        reward_value=data.get("ga_reward_value"),
        winners_count=data.get("ga_winners_count"),
        condition_type="combo",
        condition_value=combo_value,
        announce_at=dt_utc_announce,
        finalize_at=dt_utc_finalize,
        status="created"
    )
    db_session.add(new_ga)
    await db_session.commit()
    await state.clear()

    t_name = settings.parsed_titles.get(title_id).name
    if ticket_id == 0:
        cond_text = f"🎖️ Наличие титула от **'{t_name}'** и выше (Вход открытый, без билетов)."
    else:
        ticket_item = await db_session.get(ShopItem, ticket_id)
        ticket_name = ticket_item.name if ticket_item else "Билет"
        cond_text = f"🎖️ Титул от **'{t_name}'** + 🎟️ Билет **'{ticket_name}'**."

    await message.answer(
        f"🎉 **Розыгрыш добавлен в календарную сетку!**\n\n"
        f"🔒 **Критерий:** {cond_text}\n"
        f"📢 **Анонс ({user_tz_str}):** {data.get('ga_raw_local_announce')}\n"
        f"🛑 **Финал ({user_tz_str}):** {text_input}\n\n"
        f"⚙️ Бот успешно распознал ваш часовой пояс, перевел время в UTC сервера "
        f"и передал ивент фоновому планировщику задач APScheduler.",
    )
    await send_giveaways_list_page(message, db_session, db_user, page=1)


@router.callback_query(F.data == "ga_cancel")
async def process_ga_cancel(callback: CallbackQuery, state: FSMContext, db_user: User, db_session: AsyncSession):
    await state.clear()
    await callback.answer("❌ Создание розыгрыша отменено.")
    await send_giveaways_list_page(callback, db_session, db_user, page=1)

