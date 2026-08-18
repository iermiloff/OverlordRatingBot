import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database.models import User, ShopItem, StockUnit

router = Router(name="manager_users_router")
logger = logging.getLogger(__name__)

# --- 👥 ГЛАВНЫЙ СПИСОК ПОЛЬЗОВАТЕЛЕЙ ДЛЯ АДМИНА ---

@router.callback_query(F.data.startswith("mg_users_page:"))
async def cmd_manager_users_list(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    """Вывод списка участников экосистемы с постраничной пагинацией."""
    if not is_manager: return
    
    page = int(callback.data.split(":")[1])
    limit = 6
    offset = (page - 1) * limit

    
    count_q = select(func.count(User.tg_id))
    total = (await db_session.execute(count_q)).scalar() or 0
    
    users_q = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
    users = (await db_session.execute(users_q)).scalars().all()
    
    text = (
        "👥 **Управление пользователями системы**\n\n"
        f"Всего зарегистрировано участников: **{total}** юзеров.\n"
        f"Текущая страница в админке: `{page}`"
    )
    
    buttons = []
    for u in users:
        ban_tag = " [🚫 BAN]" if u.is_banned else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"👤 @{u.username or u.tg_id} | 💎 {u.current_rating}{ban_tag}", 
                callback_data=f"mg_u_view:{u.tg_id}:{page}"
            )
        ])
        
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_users_page:{page-1}"))
    if page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"mg_users_page:{page+1}"))
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([InlineKeyboardButton(text="↩️ Назад в корень меню", callback_data="main_menu_manager")])
    
    try:
        await callback.message.edit_text(
            text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown"
        )
    except Exception:
        await callback.answer()

# --- 🔎 ДЕТАЛЬНЫЙ АУДИТ ПРОФИЛЯ ЮЗЕРА ---

@router.callback_query(F.data.startswith("mg_u_view:"))
async def process_manager_user_view(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    parts = callback.data.split(":")
    # ✅ СТРОГО ИСПРАВЛЕНО: Добавлены индексы элементов списка
    user_id = int(parts[1])
    page = int(parts[2])
    
    user = await db_session.get(User, user_id)
    if not user:
        await callback.answer("❌ Юзер не найден в СУБД!", show_alert=True)
        return
        
    # Считаем количество купленных/выигранных предметов на Складе ERP
    inv_cnt_q = select(func.count(StockUnit.id)).where(
        and_(StockUnit.owner_id == user_id, StockUnit.status.in_(["sold", "won"]))
    )
    items_count = (await db_session.execute(inv_cnt_q)).scalar() or 0
    
    status_label = "🚫 ЗАБАНЕН" if user.is_banned else "🟢 Активен"
    fraud_tag = "⚠️ ПОДОЗРИТЕЛЬНЫЙ" if user.is_suspicious else "✅ Чистый"
    
    text = (
        f"👤 **Профиль участника: @{user.username or 'без_ника'}**\n\n"
        f"▪️ **Telegram ID:** <code>{user.tg_id}</code>\n"
        f"▪️ **Discord ID:** <code>{user.discord_id or 'Не привязан'}</code>\n\n"
        f"💎 **Текущий кошелек:** {user.current_rating} монет\n"
        f"🏆 **Всего заработано:** {user.lifetime_rating} поинтов опыта\n"
        f"🎒 **Предметов в инвентаре:** {items_count} шт.\n\n"
        f"⚙️ **Статусы безопасности:**\n"
        f"▪️ Системный статус: `{status_label}`\n"
        f"▪️ Скоринг антифрода: `{fraud_tag}`\n"
        f"▪️ Причина детекта: _{user.antifraud_reason or 'Нет замечаний'}_"
    )
    
    ban_btn_text = "🔓 Разбанить" if user.is_banned else "🚫 Забанить"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎁 Изменить баланс", callback_data=f"mg_u_edit_bal:{user_id}:{page}"),
            InlineKeyboardButton(text=ban_btn_text, callback_data=f"mg_u_ban_toggle:{user_id}:{page}")
        ],
        [
            InlineKeyboardButton(text="📦 Посмотреть инвентарь", callback_data=f"mg_u_inv_list:{user_id}:1:{page}"),
            InlineKeyboardButton(text="↩️ К списку", callback_data=f"mg_users_page:{page}")
        ]
    ])
    
    await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# --- ⚙️ УПРАВЛЕНИЕ БАНОМ И АДМИНСКИЙ ПРОСМОТР ИНВЕНТАРЯ ЮЗЕРА ---

@router.callback_query(F.data.startswith("mg_u_ban_toggle:"))
async def process_manager_user_ban_toggle(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    parts = callback.data.split(":")
    user_id = int(parts[1])
    page = int(parts[2])
    
    user = await db_session.get(User, user_id)
    if user:
        user.is_banned = not user.is_banned
        await db_session.commit()
        act = "забанен" if user.is_banned else "разбанен"
        await callback.answer(f"✅ Пользователь успешно {act}!", show_alert=True)
        
    await process_manager_user_view(callback, is_manager, db_session)

@router.callback_query(F.data.startswith("mg_u_inv_list:"))
async def process_manager_user_inventory_list(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    parts = callback.data.split(":")
    user_id = int(parts[1])
    inv_page = int(parts[2])
    back_page = int(parts[3])
    
    limit = 5
    offset = (inv_page - 1) * limit
    
    # Считаем предметы юзера со статусом 'sold' или 'won'
    count_q = select(func.count(StockUnit.id)).where(
        and_(StockUnit.owner_id == user_id, StockUnit.status.in_(["sold", "won"]))
    )
    total = (await db_session.execute(count_q)).scalar() or 0
    
    units_q = select(StockUnit).where(
        and_(StockUnit.owner_id == user_id, StockUnit.status.in_(["sold", "won"]))
    ).order_by(StockUnit.created_at.desc()).limit(limit).offset(offset)
    units = (await db_session.execute(units_q)).scalars().all()
    
    text = (
        f"🎒 **Аудит инвентаря пользователя (ID: {user_id})**\n\n"
        f"Всего предметов во владении: **{total}** шт.\n"
        f"Страница пагинации инвентаря: `{inv_page}`\n\n"
        f"👇 Список уникальных цифровых и физических единиц ERP:"
    )
    
    buttons = []
    for u in units:
        item_name = u.item.name if u.item else f"Предмет #{u.item_id}"
        src = "🛒" if u.purchase_source == "tg" else "🎁"
        promo_snippet = f" | 🔑 {u.serial_or_promo[:10]}..." if u.serial_or_promo else ""
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{src} ID: {u.id} | {item_name}{promo_snippet}",
                callback_data="mg_u_inv_stub" # Заглушка, чисто просмотр строки
            )
        ])
        
    nav_row = []
    if inv_page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_u_inv_list:{user_id}:{inv_page-1}:{back_page}"))
    if inv_page * limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"mg_u_inv_list:{user_id}:{inv_page+1}:{back_page}"))
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([InlineKeyboardButton(text="↩️ Вернуться к профилю", callback_data=f"mg_u_view:{user_id}:{back_page}")])
    
    await callback.message.edit_text(
        text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "mg_u_inv_stub")
async def process_mg_u_inv_stub(callback: CallbackQuery):
    await callback.answer("ℹ️ Это информационная строка инвентаря юзера.", show_alert=True)
