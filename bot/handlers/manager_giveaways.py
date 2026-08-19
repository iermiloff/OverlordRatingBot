import logging
import zoneinfo
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from config import settings
from database.models import User, ShopItem, Giveaway
from bot.states import ManagerGiveawaySetup

router = Router(name="manager_giveaways_router")
logger = logging.getLogger(__name__)

def parse_manager_time(text_input: str, user_tz: str) -> datetime:
    """Конвертирует локальное время менеджера в UTC для СУБД."""
    local_dt = datetime.strptime(text_input.strip(), "%d.%m.%Y %H:%M")
    local_dt = local_dt.replace(tzinfo=zoneinfo.ZoneInfo(user_tz))
    return local_dt.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)

@router.callback_query(ManagerGiveawaySetup.waiting_for_winners)
@router.message(ManagerGiveawaySetup.waiting_for_winners)
async def process_ga_winners(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число победителей:")
        return
    await state.update_data(ga_winners=int(message.text.strip()))
    
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎖️ Свободный (по Титулу)", callback_data="mg_ga_cond:title"),
            InlineKeyboardButton(text="🎟️ Платный (по Билету)", callback_data="mg_ga_cond:ticket")
        ]
    ])
    await message.answer("🎉 **Шаг 4:** Выберите формат участия в лотерее:", reply_markup=kb)

@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_type, F.data.startswith("mg_ga_cond:"))
async def process_ga_condition_type(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    cond_type = callback.data.split(":")[1]
    await state.update_data(ga_cond_type=cond_type)
    
    if cond_type == "title":
        await state.set_state(ManagerGiveawaySetup.waiting_for_title)
        buttons = []
        for t_id, t_info in settings.parsed_titles.items():
            buttons.append([InlineKeyboardButton(text=f"🎖️ {t_info.name}", callback_data=f"mg_ga_title:{t_id}")])
        await callback.message.edit_text("🎉 **Шаг 4.1:** Минимальный титул для участия:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await state.set_state(ManagerGiveawaySetup.waiting_for_ticket)
        t_q = select(ShopItem).where(and_(ShopItem.is_ticket == True, ShopItem.is_deleted == False))
        tickets = (await db_session.execute(t_q)).scalars().all()
        
        if not tickets:
            await callback.answer("❌ В магазине нет созданных лотерейных билетов!", show_alert=True)
            return
            
        buttons = []
        for t in tickets:
            buttons.append([InlineKeyboardButton(text=f"🎟️ {t.name} ({t.price} XP)", callback_data=f"mg_ga_ticket:{t.id}")])
        await callback.message.edit_text("🎉 **Шаг 4.1:** Выберите билет допуска:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(ManagerGiveawaySetup.waiting_for_title, F.data.startswith("mg_ga_title:"))
async def process_ga_title_choice(callback: CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split(":")[1])
    await state.update_data(ga_cond_val=t_id)
    await state.set_state(ManagerGiveawaySetup.waiting_for_announce_time)
    await callback.message.edit_text("📅 **Шаг 5:** Время **АНОНСА** в группы\nФормат строго: `ДД.ММ.ГГГГ ЧХ:ММ` (напр. `19.08.2026 18:00`):")

@router.callback_query(ManagerGiveawaySetup.waiting_for_ticket, F.data.startswith("mg_ga_ticket:"))
async def process_ga_ticket_choice(callback: CallbackQuery, state: FSMContext):
    ticket_item_id = int(callback.data.split(":")[1])
    await state.update_data(ga_cond_val=ticket_item_id)
    await state.set_state(ManagerGiveawaySetup.waiting_for_announce_time)
    await callback.message.edit_text("📅 **Шаг 5:** Время **АНОНСА** в группы\nФормат строго: `ДД.ММ.ГГГГ ЧХ:ММ` (напр. `19.08.2026 18:00`):")

@router.message(ManagerGiveawaySetup.waiting_for_announce_time)
async def process_ga_announce_time(message: Message, state: FSMContext, db_user: User):
    try:
        user_tz = db_user.timezone or "UTC"
        utc_announce = parse_manager_time(message.text, user_tz)
        await state.update_data(ga_announce_at=utc_announce)
        await state.set_state(ManagerGiveawaySetup.waiting_for_finalize_time)
        await message.answer("🏁 **Шаг 5.1:** Время **ФИНАЛА** лотереи\nФормат строго: `ДД.ММ.ГГГГ ЧХ:ММ` (напр. `20.08.2026 21:00`):")
    except ValueError:
        await message.answer("❌ Неверный формат! Пишите строго по шаблону: `19.08.2026 18:00`")

@router.message(ManagerGiveawaySetup.waiting_for_finalize_time)
async def process_ga_finalize_time(message: Message, state: FSMContext, db_user: User, db_session: AsyncSession):
    try:
        user_tz = db_user.timezone or "UTC"
        utc_finalize = parse_manager_time(message.text, user_tz)
        data = await state.get_data()
        
        if utc_finalize <= data.get("ga_announce_at"):
            await message.answer("❌ Время итогов должно быть позже времени анонса!")
            return
            
        new_ga = Giveaway(
            reward_type=str(data.get("ga_type")),
            reward_value=data.get("ga_val"),
            winners_count=data.get("ga_winners"),
            condition_type=str(data.get("ga_cond_type")),
            condition_value=str(data.get("ga_cond_val")),
            announce_at=data.get("ga_announce_at"),
            finalize_at=utc_finalize,
            status="created"
        )
        db_session.add(new_ga)
        await db_session.commit()
        await state.clear()
        
        await message.answer("✅ **Умный розыгрыш успешно запланирован в СУБД!**")
    except ValueError:
        await message.answer("❌ Неверный формат! Пишите строго по шаблону: `20.08.2026 21:00`")

