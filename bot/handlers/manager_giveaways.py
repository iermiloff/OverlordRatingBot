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
    if not is_manager: return
    
    active_q = select(Giveaway).where(Giveaway.status.in_(["created", "active"]))
    active_gas = (await db_session.execute(active_q)).scalars().all()
    
    text = (
        "🎉 **No-Code Панель Управления Лотереями**\n\n"
        "Планируйте умные розыгрыши с привязкой к билетам "
        "и титулам чата. Все таймеры работают строго по UTC.\n\n"
        f"🔥 Сейчас запущено/запланировано лотерей: **{len(active_gas)}** шт."
    )
    
    kb = [[InlineKeyboardButton(text="➕ Запланировать новый розыгрыш", callback_data="mg_giveaway_create_start")]]
    
    for ga in active_gas:
        status_lbl = "📡 Ждет анонса" if ga.status == "created" else "⏳ Идет сбор логов"
        kb.append([InlineKeyboardButton(text=f"🎁 #{ga.id} | {ga.reward_value} ({status_lbl})", callback_data=f"mg_ga_view_card:{ga.id}")])
        
    kb.append([InlineKeyboardButton(text="↩️ Вернуться в корень админки", callback_data="main_menu_manager")])
    
    try: await callback.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    except Exception: pass
    await callback.answer()

# --- 🏁 СТАРТ No-Code КОНСТРУКТОРА (ИНТЕРАКТИВНЫЙ ХОЛСТ) ---

@router.callback_query(F.data == "mg_giveaway_create_start")
async def process_mg_giveaway_create_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.clear()
    await state.set_state(ManagerGiveawaySetup.waiting_for_type)
    
    # Запоминаем ID сообщения-холста, чтобы плавно перерисовывать его
    await state.update_data(canvas_msg_id=callback.message.message_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Валюта (Рейтинг)", callback_data="mg_ga_type_set:rating"),
            InlineKeyboardButton(text="🎒 Мерч или Другое", callback_data="mg_ga_type_set:item")
        ],
        [InlineKeyboardButton(text="↩️ Отменить и назад", callback_data="mg_giveaways_main_menu")]
    ])
    await callback.message.edit_text("🏆 **Конструктор Розыгрышей**\n\n**Шаг 1/5:** Выберите тип награды:", reply_markup=kb)
    await callback.answer()

@router.callback_query(ManagerGiveawaySetup.waiting_for_type, F.data.startswith("mg_ga_type_set:"))
async def process_ga_type_choice(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    ga_type_str = callback.data.split(":")[1]
    await state.update_data(ga_type=ga_type_str)
    
    if ga_type_str == "rating":
        await state.set_state(ManagerGiveawaySetup.waiting_for_value)
        await callback.message.edit_text("🎁 **Шаг 2/5:** Введите **количество поинтов**, которое получит победитель (целое число):")
    else:
        # ✅ БЕЗУПРЕЧНЫЙ No-Code ВЫБОР: Вытаскиваем товары со склада вместо ручного ввода
        await state.set_state(ManagerGiveawaySetup.waiting_for_value)
        items_q = select(ShopItem).where(and_(ShopItem.is_ticket == False, ShopItem.is_deleted == False))
        items = (await db_session.execute(items_q)).scalars().all()
        
        if not items:
            await callback.answer("❌ На Складе ERP нет созданных товаров мерча!", show_alert=True)
            return
            
        buttons = []
        for item in items:
            buttons.append([InlineKeyboardButton(text=f"🛍️ {item.name}", callback_data=f"mg_ga_item_set:{item.name}")])
        buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="mg_giveaway_create_start")])
        
        await callback.message.edit_text("🎁 **Шаг 2/5:** Выберите целевой **Мерч со Склада** для розыгрыша:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(ManagerGiveawaySetup.waiting_for_value, F.data.startswith("mg_ga_item_set:"))
async def process_ga_item_choice_save(callback: CallbackQuery, state: FSMContext):
    """Атомарно сохраняет имя выбранного с инлайн-кнопки товара."""
    item_name = callback.data.split(":")[1]
    await state.update_data(ga_val=item_name)
    
    await state.set_state(ManagerGiveawaySetup.waiting_for_winners)
    await callback.message.edit_text("👥 **Шаг 3/5:** Введите **количество победителей** (целое число):")
    await callback.answer()

@router.message(ManagerGiveawaySetup.waiting_for_value)
async def process_ga_value_input(message: Message, state: FSMContext):
    """Шаг 2.1: Срабатывает только при вводе числа поинтов вручную."""
    data = await state.get_data()
    canvas_id = data.get("canvas_msg_id")
    text = message.text.strip()
    
    # 🧼 ЗАЧИСТКА МУСОРА: Удаляем введенный текст со смартфона
    try: await message.delete()
    except Exception: pass
    
    if not text.isdigit():
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, message_id=canvas_id,
                text="❌ Введите корректное целое число поинтов:"
            )
        except Exception: pass
        return
        
    await state.update_data(ga_val=text)
    await state.set_state(ManagerGiveawaySetup.waiting_for_winners)
    
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id, message_id=canvas_id,
            text="👥 **Шаг 3/5:** Введите **количество победителей** (целое число):"
        )
    except Exception: pass


@router.message(ManagerGiveawaySetup.waiting_for_winners)
async def process_ga_winners(message: Message, state: FSMContext):
    """Шаг 3/5 финал: Ловит количество победителей и перерисовывает инлайн-холст."""
    data = await state.get_data()
    canvas_id = data.get("canvas_msg_id")
    text = message.text.strip()
    
    # 🧼 ЗАЧИСТКА МУСОРА
    try: await message.delete()
    except Exception: pass
    
    if not text.isdigit():
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, message_id=canvas_id,
                text="❌ Введите целое число победителей:"
            )
        except Exception: pass
        return
        
    await state.update_data(ga_winners=int(text))
    await state.set_state(ManagerGiveawaySetup.waiting_for_condition_type)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🆓 Бесплатный вход (из чата)", callback_data="mg_ga_cond:free"),
            InlineKeyboardButton(text="🎟️ Вход по Билету магазина", callback_data="mg_ga_cond:ticket")
        ],
        [InlineKeyboardButton(text="↩️ Отменить и назад", callback_data="mg_giveaways_main_menu")]
    ])
    
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id, message_id=canvas_id,
            text="🎉 **Шаг 4/5:** Выберите финансовое условие лотереи:",
            reply_markup=kb
        )
    except Exception: pass


@router.callback_query(ManagerGiveawaySetup.waiting_for_condition_type, F.data.startswith("mg_ga_cond:"))
async def process_ga_condition_type(callback: CallbackQuery, state: FSMContext, db_session: AsyncSession):
    """Шаг 4/5 финал: Развилка No-Code условий допуска участников."""
    cond_type_str = callback.data.split(":")[1]
    await state.update_data(ga_cond_type=cond_type_str)
    
    if cond_type_str == "free":
        await state.update_data(ga_cond_val="0")
        await state.set_state(ManagerGiveawaySetup.waiting_for_title)
        buttons = []
        for t_id, t_info in settings.parsed_titles.items():
            buttons.append([InlineKeyboardButton(text=f"🎖️ {t_info.name}", callback_data=f"mg_ga_title:{t_id}")])
        buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="mg_giveaway_create_start")])
        
        await callback.message.edit_text(
            "🎉 **Шаг 5/5:** Укажите минимальный ТИТУЛ опыта участников чата:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        await state.set_state(ManagerGiveawaySetup.waiting_for_ticket)
        t_q = select(ShopItem).where(and_(ShopItem.is_ticket == True, ShopItem.is_deleted == False))
        tickets = (await db_session.execute(t_q)).scalars().all()
        
        if not tickets:
            await callback.answer("❌ На Складе ERP нет билетов! Создайте их.", show_alert=True)
            return
            
        buttons = []
        for t in tickets:
            buttons.append([InlineKeyboardButton(text=f"🎟️ {t.name}", callback_data=f"mg_ga_ticket:{t.id}")])
        buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="mg_giveaway_create_start")])
        
        await callback.message.edit_text(
            "🎉 **Шаг 4.1:** Выберите входной билет из ассортимента витрины:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    await callback.answer()


@router.callback_query(ManagerGiveawaySetup.waiting_for_ticket, F.data.startswith("mg_ga_ticket:"))
async def process_ga_ticket_choice(callback: CallbackQuery, state: FSMContext):
    """Ловит ID билета и переводит на сквозной ценз несгораемого ранга."""
    ticket_item_id = int(callback.data.split(":")[1])
    await state.update_data(ga_cond_val=ticket_item_id)
    
    await state.set_state(ManagerGiveawaySetup.waiting_for_title)
    buttons = []
    for t_id, t_info in settings.parsed_titles.items():
        buttons.append([InlineKeyboardButton(text=f"🎖️ {t_info.name}", callback_data=f"mg_ga_title:{t_id}")])
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="mg_giveaway_create_start")])
    
    await callback.message.edit_text(
        "🎉 **Шаг 5/5:** Дополнительно укажите минимальный ТИТУЛ опыта для допуска:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(ManagerGiveawaySetup.waiting_for_title, F.data.startswith("mg_ga_title:"))
async def process_ga_title_choice(callback: CallbackQuery, state: FSMContext):
    """Финал Шага 5: Сохранение ценза ранга и переход к вводу дат времени."""
    t_id = int(callback.data.split(":")[1])
    await state.update_data(ga_min_title=t_id)
    await state.set_state(ManagerGiveawaySetup.waiting_for_announce_time)
    
    await callback.message.edit_text(
        "📅 **Установка дат планировщика (Воркер UTC)**\n\n"
        "Введите дату и время публикации анонса в группы.\n"
        "Формат строго: `ДД.ММ.ГГГГ ЧХ:ММ` (напр. `19.08.2026 18:00`):"
    )
    await callback.answer()


@router.message(ManagerGiveawaySetup.waiting_for_announce_time)
async def process_ga_announce_time(message: Message, state: FSMContext, db_user: User):
    data = await state.get_data()
    canvas_id = data.get("canvas_msg_id")
    
    # 🧼 ЗАЧИСТКА МУСОРА
    try: await message.delete()
    except Exception: pass
    
    try:
        user_tz = db_user.timezone or "UTC"
        utc_announce = parse_manager_time(message.text, user_tz)
        await state.update_data(ga_announce_at=utc_announce)
        await state.set_state(ManagerGiveawaySetup.waiting_for_finalize_time)
        
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, message_id=canvas_id,
                text="🏁 **Финал сбора активности лотереи**\n\nВведите дату и время завершения розыгрыша.\nФормат строго: `ДД.ММ.ГГГГ ЧХ:ММ` (напр. `20.08.2026 21:00`):"
            )
        except Exception: pass
    except ValueError:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, message_id=canvas_id,
                text="❌ Неверный формат! Пишите строго по шаблону: `19.08.2026 18:00`"
            )
        except Exception: pass


@router.message(ManagerGiveawaySetup.waiting_for_finalize_time)
async def process_ga_finalize_time(message: Message, state: FSMContext, db_user: User, db_session: AsyncSession):
    data = await state.get_data()
    canvas_id = data.get("canvas_msg_id")
    
    # 🧼 ЗАЧИСТКА МУСОРА
    try: await message.delete()
    except Exception: pass
    
    try:
        user_tz = db_user.timezone or "UTC"
        utc_finalize = parse_manager_time(message.text, user_tz)
        
        if utc_finalize <= data.get("ga_announce_at"):
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id, message_id=canvas_id,
                    text="❌ Время итогов должно быть строго позже времени анонса!"
                )
            except Exception: pass
            return

        # Исключаем попадание списков в СУБД через жесткое строковое приведение
        raw_r_type = str(data.get("ga_type"))
        raw_c_type = str(data.get("ga_cond_type"))
        
        clean_reward_type = "rating" if "rating" in raw_r_type else "item"
        clean_cond_type = "ticket" if "ticket" in raw_c_type else "free"
            
        new_ga = Giveaway(
            reward_type=clean_reward_type,
            reward_value=str(data.get("ga_val")).strip(),
            winners_count=int(data.get("ga_winners")),
            condition_type=clean_cond_type,
            condition_value=str(data.get("ga_cond_val")).strip(),
            min_title_id=int(data.get("ga_min_title")),
            announce_at=data.get("ga_announce_at"),
            finalize_at=utc_finalize,
            status="created"
        )
        db_session.add(new_ga)
        await db_session.commit()
        await state.clear()
        
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Назад в Панель Розыгрышей", callback_data="mg_giveaways_main_menu")]
        ])
        
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=canvas_id,
                text="🎉 **Умный розыгрыш успешно запланирован в СУБД!**\n\nВсе тайм-лимиты переведены во внутренний UTC-формат планировщика. Анонс вылетит автоматически.",
                reply_markup=back_kb
            )
        except Exception: pass
    except ValueError:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id, message_id=canvas_id,
                text="❌ Неверный формат! Пишите строго по шаблону: `20.08.2026 21:00`"
            )
        except Exception: pass

