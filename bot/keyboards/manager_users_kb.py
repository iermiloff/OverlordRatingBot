from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import settings

def get_users_list_keyboard(users: list, page: int, has_next: bool) -> InlineKeyboardMarkup:
    """Список пользователей с обязательной кнопкой выхода в главное меню."""
    buttons = []
    
    for u in users:
        username_text = f" (@{u.username})" if u.username else ""
        buttons.append([
            InlineKeyboardButton(text=f"👤 {u.full_name}{username_text}", callback_data=f"mg_user_view:{u.tg_id}:{page}")
        ])
        
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mg_users_page:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"mg_users_page:{page+1}"))
        
    if nav_row:
        buttons.append(nav_row)

    # ИСПРАВЛЕНО: Менеджер больше не застрянет на экране списка пользователей
    buttons.append([InlineKeyboardButton(text="↩️ Главное меню админки", callback_data="main_menu_manager")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_user_profile_keyboard(user_id: int, page: int) -> InlineKeyboardMarkup:
    """Действия внутри карточки конкретного пользователя."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Изменить баланс рейтинга", callback_data=f"mg_user_rate:{user_id}:{page}")],
        [InlineKeyboardButton(text="🎁 Выдать товар (Подарок)", callback_data=f"mg_user_gift:{user_id}:{page}")],
        [InlineKeyboardButton(text="↩️ Назад к списку", callback_data=f"mg_users_page:{page}")]
    ])

def get_gift_items_keyboard(items: list, user_id: int, page: int) -> InlineKeyboardMarkup:
    """Список товаров для бесплатной выдачи подарка."""
    buttons = []
    for item in items:
        buttons.append([
            InlineKeyboardButton(text=f"📦 {item.name} ({item.price} {settings.CURRENCY_NAME})", 
                                 callback_data=f"mg_gift_confirm:{user_id}:{item.id}:{page}")
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"mg_user_view:{user_id}:{page}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- 🎁 No-Code НАЧИСЛЕНИЕ / СПИСАНИЕ БАЛАНСА АДМИНОМ ---

@router.callback_query(F.data.startswith("mg_u_edit_bal:"))
async def process_mg_u_edit_bal_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    """Запуск FSM-ожидания ввода нового баланса."""
    if not is_manager: return
    parts = callback.data.split(":")
    user_id = int(parts[1])
    page = int(parts[2])
    
    await state.update_data(edit_user_id=user_id, edit_page=page)
    
    # Регистрируем стейт динамически (проверь, чтобы State был в bot.states)
    from bot.states import ManagerCustomRewardSetup 
    await state.set_state(ManagerCustomRewardSetup.waiting_for_value)
    
    await callback.message.answer(
        "💎 **Изменение баланса пользователя**\n\n"
        "Введите число поинтов. Если нужно **начислить**, пишите просто число (напр. `500`). "
        "Если нужно **списать** — пишите со знаком минус (напр. `-200`):"
    )
    await callback.answer()

@router.message(F.state == "ManagerCustomRewardSetup:waiting_for_value")
async def process_mg_u_edit_bal_save(message: Message, state: FSMContext, db_session: AsyncSession):
    """Атомарное применение изменений баланса в СУБД."""
    text_input = message.text.strip()
    
    # Проверяем на корректность ввода числа (включая знак минус)
    is_negative = text_input.startswith("-")
    clean_text = text_input.replace("-", "")
    
    if not clean_text.isdigit():
        await message.answer("❌ Введите корректное целое число:")
        return
        
    delta = int(text_input)
    data = await state.get_data()
    user_id = data.get("edit_user_id")
    page = data.get("edit_page")
    
    user = await db_session.get(User, user_id)
    if not user:
        await message.answer("❌ Пользователь не найден в базе данных.")
        await state.clear()
        return
        
    # Применяем изменения к кошелькам экосистемы
    user.current_rating += delta
    if delta > 0:
        user.lifetime_rating += delta # Опыт увеличиваем только при начислении
        
    await db_session.commit()
    await state.clear()
    
    await message.answer(
        f"✅ **Баланс успешно обновлен!**\n\n"
        f"👤 Юзер: @{user.username or user.tg_id}\n"
        f"📊 Изменение: `{delta:+}` {settings.CURRENCY_NAME}.\n"
        f"💰 Новый кошелек: **{user.current_rating}** монет."
    )
    
    # Уведомляем пользователя в ЛС об изменении счета
    try:
        msg_type = f"начислено ➕{delta}" if delta > 0 else f"списано ➖{abs(delta)}"
        await message.bot.send_message(
            chat_id=user.tg_id,
            text=f"📊 **Баланс изменен администрацией!**\n\nВам {msg_type} {settings.CURRENCY_NAME}.\nТекущий счет: **{user.current_rating}** монет."
        )
    except Exception: pass

