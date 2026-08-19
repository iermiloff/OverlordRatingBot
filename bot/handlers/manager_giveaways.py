import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import Giveaway, User, ChatConfig, ShopItem, StockUnit
from bot.states import ManagerGiveawaySetup # Убедись, что стейт есть в states.py

router = Router(name="manager_giveaways_router")
logger = logging.getLogger(__name__)

# --- 📋 КОРЕНЬ МЕНЮ РОЗЫГРЫШЕЙ ---

@router.callback_query(F.data == "mg_giveaways_panel")
async def cmd_manager_giveaways_main(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    
    # Считаем активные лотереи
    q = select(func.count(Giveaway.id)).where(Giveaway.status != "finished")
    active_cnt = (await db_session.execute(q)).scalar() or 0
    
    text = (
        "🎉 **Управление Розыгрышами и Лотереями**\n\n"
        "Здесь вы можете запускать автоматические розыгрыши мерча "
        "или рейтинга среди участников чата с привязкой к титулам.\n\n"
        f"Активных лотерей прямо сейчас: **{active_cnt}** шт."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Запустить розыгрыш", callback_data="mg_ga_create_start")],
        [InlineKeyboardButton(text="↩️ Вернуться к админке", callback_data="main_menu_manager")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

# --- ➕ FSM-КОНСТРУКТОР РОЗЫГРЫША ---

@router.callback_query(F.data == "mg_ga_create_start")
async def process_ga_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerGiveawaySetup.waiting_for_type)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 Валюта рейтинга", callback_data="mg_ga_type:rating"),
            InlineKeyboardButton(text="🎒 Товар/Мерч со Склада", callback_data="mg_ga_type:item")
        ]
    ])
    await callback.message.edit_text("🎉 **Шаг 1/5:** Выберите тип приза:", reply_markup=kb)
    await callback.answer()

@router.callback_query(ManagerGiveawaySetup.waiting_for_type, F.data.startswith("mg_ga_type:"))
async def process_ga_type(callback: CallbackQuery, state: FSMContext):
    g_type = callback.data.split(":")
    await state.update_data(ga_type=g_type)
    await state.set_state(ManagerGiveawaySetup.waiting_for_value)
    
    p = "Введите **число монет**:" if g_type == "rating" else "Введите **Название товара**, строго как на Складе:"
    await callback.message.edit_text(f"🎉 **Шаг 2/5:** {p}", parse_mode="Markdown")
    await callback.answer()

@router.message(ManagerGiveawaySetup.waiting_for_value)
async def process_ga_value(message: Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.strip()
    
    if data.get("ga_type") == "rating" and not text.isdigit():
        await message.answer("❌ Введите целое число монет:")
        return
        
    await state.update_data(ga_val=text)
    await state.set_state(ManagerGiveawaySetup.waiting_for_winners)
    await message.answer("🎉 **Шаг 3/5:** Сколько будет **победителей**?")

@router.message(ManagerGiveawaySetup.waiting_for_winners)
async def process_ga_winners(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число победителей:")
        return
    await state.update_data(ga_winners=int(message.text.strip()))
    await state.set_state(ManagerGiveawaySetup.waiting_for_title)
    
    # Генерация кнопок выбора минимального титула
    from bot.keyboards.manager_activities_kb import (
        get_titles_choice_keyboard
    )
    # Используем кастомный префикс callback, чтобы не путать со старыми
    buttons = []
    for t_id, t_info in settings.parsed_titles.items():
        buttons.append([
            InlineKeyboardButton(
                text=f"🎖️ {t_info.name}", 
                callback_data=f"mg_ga_title:{t_id}"
            )
        ])
    await message.answer(
        "🎉 **Шаг 4/5:** Минимальный **титул** для участия:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

# Измени стейты в bot/states.py (или допиши в верху файла):
# class ManagerGiveawaySetup(StatesGroup):
#     ...
#     waiting_for_title = State()
#     waiting_for_announce_time = State() # Шаг 4: Время анонса
#     waiting_for_finalize_time = State() # Шаг 5: Время итогов

from datetime import datetime
import zoneinfo # Для нативной работы с таймзонами менеджеров

def parse_manager_time(text_input: str, user_tz: str) -> datetime:
    """Конвертирует локальное время менеджера в UTC для СУБД."""
    # Ожидаем формат "ДД.ММ.ГГГГ ЧХ:ММ" (напр. "19.08.2026 18:00")
    local_dt = datetime.strptime(text_input.strip(), "%d.%m.%Y %H:%M")
    # Привязываем локальную таймзону (напр. Europe/Moscow)
    local_dt = local_dt.replace(tzinfo=zoneinfo.ZoneInfo(user_tz))
    # Переводим в чистый UTC для сервера
    return local_dt.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)


@router.callback_query(ManagerGiveawaySetup.waiting_for_title, F.data.startswith("mg_ga_title:"))
async def process_ga_title(callback: CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split(":"))
    await state.update_data(ga_title=t_id)
    
    await state.set_state(ManagerGiveawaySetup.waiting_for_announce_time)
    await callback.message.edit_text(
        "📅 **Шаг 4/5: Время АНОНСА розыгрыша**\n\n"
        "Введите дату и время, когда бот должен опубликовать пост-анонс в чаты.\n"
        "Формат строго: `ДД.ММ.ГГГГ ЧХ:ММ` (например: `19.08.2026 18:00`):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ManagerGiveawaySetup.waiting_for_announce_time)
async def process_ga_announce_time(message: Message, state: FSMContext, db_user: User):
    try:
        user_tz = db_user.timezone or "UTC"
        utc_announce = parse_manager_time(message.text, user_tz)
        await state.update_data(ga_announce_at=utc_announce)
        
        await state.set_state(ManagerGiveawaySetup.waiting_for_finalize_time)
        await message.answer(
            "🏁 **Шаг 5/5: Время ПОДВЕДЕНИЯ ИТОГОВ**\n\n"
            "Введите дату и время, когда планировщик определит победителей.\n"
            "Формат строго: `ДД.ММ.ГГГГ ЧХ:ММ` (например: `20.08.2026 21:00`):",
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Неверный формат! Напишите строго по шаблону: `19.08.2026 18:00`")


@router.message(ManagerGiveawaySetup.waiting_for_finalize_time)
async def process_ga_finalize_time(message: Message, state: FSMContext, db_user: User, db_session: AsyncSession):
    try:
        user_tz = db_user.timezone or "UTC"
        utc_finalize = parse_manager_time(message.text, user_tz)
        data = await state.get_data()
        
        if utc_finalize <= data.get("ga_announce_at"):
            await message.answer("❌ Время итогов должно быть строго ПОЗЖЕ времени анонса!")
            return
            
        new_ga = Giveaway(
            reward_type=str(data.get("ga_type")),
            reward_value=data.get("ga_val"),
            winners_count=data.get("ga_winners"),
            condition_value=str(data.get("ga_title")),
            announce_at=data.get("ga_announce_at"), # Время публикации
            finalize_at=utc_finalize,               # Время сбора логов и финиша
            status="created"                         # Статус ожидания анонса
        )
        db_session.add(new_ga)
        await db_session.commit()
        await state.clear()
        
        await message.answer(
            f"✅ **Умный розыгрыш успешно запланирован!**\n\n"
            f"📡 Анонс в группы (UTC): `{data.get('ga_announce_at').strftime('%d.%m %H:%M')}`\n"
            f"🏆 Финал и логи (UTC): `{utc_finalize.strftime('%d.%m %H:%M')}`\n\n"
            f"Планировщик сделает всё автоматически."
        )
    except ValueError:
        await message.answer("❌ Неверный формат! Напишите строго по шаблону: `20.08.2026 21:00`")


@router.callback_query(F.data == "mg_ga_cancel")
async def process_ga_cancel(callback: CallbackQuery, state: FSMContext):
    """Сброс состояния конструктора лотерей и возврат в меню."""
    await state.clear()
    await callback.message.edit_text("❌ Создание розыгрыша отменено.")
    await callback.answer()
