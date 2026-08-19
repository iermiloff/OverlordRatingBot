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


# --- 📊 ГЛАВНАЯ No-Code ПАНЕЛЬ УПРАВЛЕНИЯ РОЗЫГРЫШАМИ ---

@router.callback_query(F.data == "mg_giveaways_main_menu")
async def cmd_manager_giveaways_dashboard(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    """Вывод панели лотерей: просмотр активных и запуск новых."""
    if not is_manager: return
    
    # Атомарно считаем, сколько лотерей сейчас крутится в базе в статусах ожидания или сбора логов
    active_q = select(Giveaway).where(Giveaway.status.in_(["created", "active"]))
    active_gas = (await db_session.execute(active_q)).scalars().all()
    
    text = (
        "🎉 **No-Code Панель Управления Лотереями**\n\n"
        "Здесь вы можете планировать умные розыгрыши с привязкой к билетам "
        "из магазина и несгораемым титулам чата. Все таймеры работают строго по UTC.\n\n"
        f"🔥 Сейчас запущено/запланировано лотерей: **{len(active_gas)}** шт."
    )
    
    # Формируем аккуратную инлайн-сетку кнопок управления
    kb = [
        [
            InlineKeyboardButton(text="➕ Запланировать новый розыгрыш", callback_data="mg_giveaway_create_start")
        ]
    ]
    
    # Добавляем в ленту кнопки быстрых карточек активных лотерей (если они есть)
    for ga in active_gas:
        status_lbl = "📡 Ждет анонса" if ga.status == "created" else "⏳ Идет сбор логов"
        kb.append([
            InlineKeyboardButton(
                text=f"🎁 #{ga.id} | {ga.reward_value} ({status_lbl})",
                callback_data=f"mg_ga_view_card:{ga.id}"
            )
        ])
        
    kb.append([InlineKeyboardButton(text=" Вернуться в корень админки", callback_data="main_menu_manager")])
    
    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="Markdown"
    )
    await callback.answer()



@router.callback_query(F.data == "mg_giveaway_create_start")
async def process_mg_giveaway_create_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    """Перенаправленный стартер шагов конструктора."""
    if not is_manager: return
    
    # Жестко включаем стейт Шага 1
    await state.set_state(ManagerGiveawaySetup.waiting_for_type)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=" Валюта (Рейтинг)", callback_data="mg_ga_type_set:rating"),
            InlineKeyboardButton(text=" Мерч/Другое", callback_data="mg_ga_type_set:item")
        ],
        [
            InlineKeyboardButton(text="↩️ Назад в меню лотерей", callback_data="mg_giveaways_main_menu")
        ]
    ])
    
    await callback.message.edit_text(
        "🏆 **Конструктор Лотерей**\n\n"
        "**Шаг 1/5:** Выберите тип награды для участников чата:",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(ManagerGiveawaySetup.waiting_for_type, F.data.startswith("mg_ga_type_set:"))
async def process_ga_type_choice(callback: CallbackQuery, state: FSMContext):
    """Сохранение типа приза с чистым извлечением строки без списков."""
    ga_type_str = callback.data.split(":")[1]
    await state.update_data(ga_type=ga_type_str)
    
    await state.set_state(ManagerGiveawaySetup.waiting_for_value)
    
    if ga_type_str == "rating":
        prompt = "Введите **количество поинтов**, которое получит победитель (целое число):"
    else:
        prompt = "Введите **название товара**, как оно написано на Складе ERP (например: `Худи Оверлорда`):"
        
    await callback.message.edit_text(f"🎁 **Шаг 2/5:** {prompt}", parse_mode="Markdown")
    await callback.answer()

@router.message(ManagerGiveawaySetup.waiting_for_value)
async def process_ga_value_input(message: Message, state: FSMContext):
    """Сохранение значения приза и переход к числу победителей."""
    data = await state.get_data()
    ga_type = data.get("ga_type")
    text = message.text.strip()
    
    if ga_type == "rating" and not text.isdigit():
        await message.answer("❌ Введите корректное целое число поинтов:")
        return
        
    await state.update_data(ga_val=text)
    await state.set_state(ManagerGiveawaySetup.waiting_for_winners)
    await message.answer("👥 **Шаг 3/5:** Введите **количество победителей** (целое число):")


@router.message(ManagerGiveawaySetup.waiting_for_winners)
async def process_ga_winners(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ Введите целое число победителеи:")
        return
    await state.update_data(ga_winners=int(message.text.strip()))
    
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_type)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🆓 Бесплатный вход (из чата)", callback_data="mg_ga_cond:free"),
            InlineKeyboardButton(text="🎟️ Вход по Билету магазина", callback_data="mg_ga_cond:ticket")
        ]
    ])
    await message.answer("🎉 **Шаг 4:** Выберите финансовое условие лотереи:", reply_markup=kb)


@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_type, F.data.startswith("mg_ga_cond:"))
async def process_ga_condition_type(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    cond_type_str = callback.data.split(":")
    await state.update_data(ga_cond_type=cond_type_str)
    
    if cond_type_str == "free":
        await state.update_data(ga_cond_val="0")
        await state.set_state(ManagerGiveawaySetup.waiting_for_title)
        buttons = []
        for t_id, t_info in settings.parsed_titles.items():
            buttons.append([InlineKeyboardButton(text=f"🎖️ {t_info.name}", callback_data=f"mg_ga_title:{t_id}")])
        await callback.message.edit_text("🎉 **Шаг 5:** Укажите минимальный ТИТУЛ опыта для допуска участников:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await state.set_state(ManagerGiveawaySetup.waiting_for_ticket)
        t_q = select(ShopItem).where(and_(ShopItem.is_ticket == True, ShopItem.is_deleted == False))
        tickets = (await db_session.execute(t_q)).scalars().all()
        
        if not tickets:
            await callback.answer("❌ В магазине нет созданных лотерейных билетов!", show_alert=True)
            return
        buttons = []
        for t in tickets:
            buttons.append([InlineKeyboardButton(text=f"🎟️ {t.name}", callback_data=f"mg_ga_ticket:{t.id}")])
        await callback.message.edit_text("🎉 **Шаг 4.1:** Выберите входной билет из ассортимента витрины:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()



@router.callback_query(ManagerGiveawaySetup.waiting_for_ticket, F.data.startswith("mg_ga_ticket:"))
async def process_ga_ticket_choice(callback: CallbackQuery, state: FSMContext):
    ticket_item_id = int(callback.data.split(":")[1])
    await state.update_data(ga_cond_val=ticket_item_id)
    
    # После выбора билета ТОЖЕ требуем указать минимальный титул!
    await state.set_state(ManagerGiveawaySetup.waiting_for_title)
    buttons = []
    for t_id, t_info in settings.parsed_titles.items():
        buttons.append([InlineKeyboardButton(text=f"🎖️ {t_info.name}", callback_data=f"mg_ga_title:{t_id}")])
    await callback.message.edit_text("🎉 **Шаг 5:** Укажите минимальный ТИТУЛ опыта, необходимый помимо билета:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(ManagerGiveawaySetup.waiting_for_title, F.data.startswith("mg_ga_title:"))
async def process_ga_title_choice(callback: CallbackQuery, state: FSMContext):
    t_id = int(callback.data.split(":")[1])
    await state.update_data(ga_min_title=t_id)
    
    await state.set_state(ManagerGiveawaySetup.waiting_for_announce_time)
    await callback.message.edit_text("📅 **Шаг 5.1:** Время **АНОНСА** розыгрыша\nФормат строго: `ДД.ММ.ГГГГ ЧХ:ММ` (напр. `19.08.2026 18:00`):")
    await callback.answer()

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
            reward_type=str(data.get("ga_type")[1]), # Вытаскиваем чистую строку приза
            reward_value=data.get("ga_val"),
            winners_count=data.get("ga_winners"),
            condition_type=str(data.get("ga_cond_type")[1]), 
            condition_value=str(data.get("ga_cond_val")),
            min_title_id=int(data.get("ga_min_title")),
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

