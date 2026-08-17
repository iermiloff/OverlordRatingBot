import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import settings
from database.models import User

router = Router(name="manager_antifraud_router")
logger = logging.getLogger(__name__)

# --- ОБРАБОТКА МГНОВЕННЫХ АЛЕРТОВ АНТИФРОДА (БАН / ПОМИЛОВАНИЕ) ---

@router.callback_query(F.data.startswith("af_confirm_ban:"))
async def process_af_callback_ban(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    """Атомарный подтвержденный бан кликера прямо из текста экстренного уведомления."""
    if not is_manager: return
    
    target_user_id = int(callback.data.split(":")[1])
    user_obj = await db_session.get(User, target_user_id)
    
    if not user_obj:
        await callback.answer("❌ Пользователь не найден в базе данных.", show_alert=True)
        return
        
    if user_obj.is_banned:
        await callback.answer("ℹ️ Этот аккаунт уже находится в черном списке.", show_alert=True)
        return

    # Включаем перманентную блокировку и сжигаем накопленную игровую валюту
    user_obj.is_banned = True
    user_obj.current_rating = 0
    user_obj.antifraud_reason = f"🔨 Забанен оверлордом за использование автоматизации кликов."
    await db_session.commit()

    # Изменяем текст карточки алерта у менеджера, удаляя кнопки управления
    try:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n"
            f"❌ <b>ВЕРДИКТ СИСТЕМЫ:</b> Нарушитель успешно заблокирован. "
            f"Его текущий кошелек полностью обнулен, начисления заморожены.",
            reply_markup=None,
            parse_mode="HTML"
        )
    except Exception: pass
    
    await callback.answer("🔨 Нарушитель отправлен в перманентный бан!", show_alert=True)


@router.callback_query(F.data.startswith("af_pardon:"))
async def process_af_callback_pardon(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    """Снятие обвинений в спаме с пользователя прямо из инлайн-карточки алерта."""
    if not is_manager: return
    
    target_user_id = int(callback.data.split(":")[1])
    user_obj = await db_session.get(User, target_user_id)
    
    if not user_obj:
        await callback.answer("❌ Пользователь не найден.", show_alert=True)
        return

    # Очищаем подозрительный статус
    user_obj.is_suspicious = False
    user_obj.antifraud_reason = None
    await db_session.commit()

    try:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n"
            f"✅ <b>ВЕРДИКТ СИСТЕМЫ:</b> Обвинения полностью сняты менеджером {callback.from_user.mention_html()}. "
            f"Пользователь помилован и продолжает участие в игровой активности.",
            reply_markup=None,
            parse_mode="HTML"
        )
    except Exception: pass
    
    await callback.answer("✅ Метки подозрительности удалены, игрок помилован.", show_alert=True)

# --- ПАНЕЛЬ РУЧНОГО МОНИТОРИНГА ВСЕХ ПОДОЗРИТЕЛЬНЫХ УЧАСТНИКОВ (CRM) ---

USERS_PER_PAGE_AF = 4

async def send_antifraud_panel_page(callback_or_message, session: AsyncSession, page: int = 1):
    """Отрисовка постраничного списка всех подозрительных учетных записей чата."""
    # Считаем общее число зафиксированных системой абузеров
    count_q = select(func.count(User.tg_id)).where(User.is_suspicious == True)
    total_suspicious = (await session.execute(count_q)).scalar() or 0

    buttons = []

    if total_suspicious == 0:
        text = (
            "🔒 **Инфраструктура математического Анти-фрода**\n\n"
            "🟢 Система работает стабильно. Кликеры и макрос-боты в чатах не зафиксированы!\n\n"
            "Все пользователи отправляют сообщения с хаотичными временными интервалами, "
            "что полностью соответствует паттернам живого человека. Дисперсия в норме."
        )
        buttons.append([InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    else:
        offset_value = (page - 1) * USERS_PER_PAGE_AF
        query = (
            select(User)
            .where(User.is_suspicious == True)
            .order_by(User.created_at.desc())
            .limit(USERS_PER_PAGE_AF)
            .offset(offset_value)
        )
        suspicious_users = (await session.execute(query)).scalars().all()
        has_next = (page * USERS_PER_PAGE_AF) < total_suspicious

        lines = [f"🚨 **Картотека подозрительных профилей (Страница {page})**\n"]
        lines.append("Ниже представлены аккаунты, у которых стандартное отклонение (σ) таймингов "
                     "сообщений упало ниже нормы 3.5 сек. Изучите метрики:\n")

        for u in suspicious_users:
            status_tag = "🔨 ЗАБАНЕН" if u.is_banned else "⏳ НА ПРОВЕРКЕ"
            lines.append(
                f"👤 <b>Юзер:</b> @{u.username or u.tg_id} | {status_tag}\n"
                f"🆔 ID: <code>{u.tg_id}</code>\n"
                f"📊 Лог системы: <i>{u.antifraud_reason or 'Не указан'}</i>\n"
            )
            
            # Ряд быстрых кнопок управления для каждого абузера прямо внутри списка
            if not u.is_banned:
                buttons.append([
                    InlineKeyboardButton(text=f"🔨 Бан ID:{u.tg_id}", callback_data=f"af_confirm_ban:{u.tg_id}"),
                    InlineKeyboardButton(text=f"✅ Помиловать ID:{u.tg_id}", callback_data=f"af_pardon:{u.tg_id}")
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(text=f"✅ Снять пермабан ID:{u.tg_id}", callback_data=f"af_pardon:{u.tg_id}")
                ])

        text = "\n".join(lines)

        # Навигационный блок пагинации списка
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"af_page:{page-1}"))
        if has_next:
            nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"af_page:{page+1}"))
        if nav_row:
            buttons.append(nav_row)

        buttons.append([InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    if isinstance(callback_or_message, CallbackQuery):
        try: await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception: await callback_or_message.answer()
    else:
        await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("af_page:"))
async def process_antifraud_panel_click(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    page = int(callback.data.split(":"))
    await send_antifraud_panel_page(callback, db_session, page=page)
    await callback.answer()

