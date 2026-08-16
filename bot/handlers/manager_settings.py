from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.models import ChatConfig, PromoChannel, User
from bot.keyboards.manager_settings_kb import get_settings_main_keyboard, get_timezone_selection_keyboard
from bot.states import ManagerSettingsPromo

router = Router(name="manager_settings_router")

async def refresh_settings_panel(callback_or_message, session: AsyncSession, manager_user: User):
    """Обновляет состояние экранной панели с выводом текущего пояса админа."""
    chats = (await session.execute(select(ChatConfig).order_by(ChatConfig.title))).scalars().all()
    promo_channels = (await session.execute(select(PromoChannel))).scalars().all()

    current_tz = manager_user.timezone or "UTC"

    text = (
        "⚙️ **Настройка чатов, промо-заданий и профиля**\n\n"
        f"🌍 Ваш текущий часовой пояс: **{current_tz}**\n"
        "_(Все розыгрыши настраиваются по вашим наручным часам!_\n\n"
        "🟢 **Учет активности в группах:**\n"
        "Кликните по кнопке чата ниже, чтобы переключить режим начисления рейтинга за сообщения.\n\n"
        "📢 **Партнерские задания:**\n"
        "Вы можете удалять старые ссылки или добавлять новые каналы."
    )
    
    reply_markup = get_settings_main_keyboard(chats, promo_channels)
    
    # Модифицируем клавиатуру настроек на лету: добавляем кнопку управления таймзоной в профиле
    tz_btn = InlineKeyboardButton(text="🌍 Сменить мой Часовой Пояс (Таймзону)", callback_data="mg_change_profile_tz")
    
    # Вставляем кнопку перед кнопкой «Назад в админку»
    if reply_markup.inline_keyboard:
        reply_markup.inline_keyboard.insert(-1, [tz_btn])

    if isinstance(callback_or_message, CallbackQuery):
        try: await callback_or_message.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception: await callback_or_message.answer()
    else:
        await callback_or_message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")


@router.callback_query(F.data == "mg_settings_panel")
async def process_mg_settings_panel_click(callback: CallbackQuery, is_manager: bool, db_user: User, db_session: AsyncSession):
    if not is_manager: return
    await refresh_settings_panel(callback, db_session, db_user)
    await callback.answer()


@router.callback_query(F.data == "mg_change_profile_tz")
async def process_open_tz_grid(callback: CallbackQuery, is_manager: bool):
    if not is_manager: return
    await callback.message.edit_text(
        "🌍 **Настройка личного часового пояса**\n\n"
        "Ниже представлен список мировых регионов. На кнопках отображается **актуальное текущее время** в каждом из них.\n\n"
        "👉 Выберите регион, время в котором **совпадает с вашим текущим временем на компьютере/телефоне**:",
        reply_markup=get_timezone_selection_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("set_profile_tz:"))
async def process_save_profile_tz(callback: CallbackQuery, is_manager: bool, db_user: User, db_session: AsyncSession):
    if not is_manager: return
    chosen_tz = callback.data.split(":")[1]

    # Сохраняем выбранный часовой пояс в профиль админа
    db_user.timezone = chosen_tz
    await db_session.commit()

    await callback.answer(f"✅ Ваш часовой пояс успешно изменен на {chosen_tz}!", show_alert=True)
    await refresh_settings_panel(callback, db_session, db_user)

@router.callback_query(F.data.startswith("mg_chat_toggle:"))
async def process_mg_chat_toggle(callback: CallbackQuery, is_manager: bool, db_user: User, db_session: AsyncSession):
    if not is_manager: return
    chat_id = int(callback.data.split(":")[1])

    chat = await db_session.get(ChatConfig, chat_id)
    if chat:
        chat.is_active = not chat.is_active
        await db_session.commit()
        status_text = "включен" if chat.is_active else "выключен"
        await callback.answer(f"ℹ️ Учет активности в чате '{chat.title}' {status_text}!")
    
    await refresh_settings_panel(callback, db_session, db_user)

@router.callback_query(F.data.startswith("mg_promo_del:"))
async def process_mg_promo_del(callback: CallbackQuery, is_manager: bool, db_user: User, db_session: AsyncSession):
    if not is_manager: return
    promo_id = int(callback.data.split(":")[1])
    
    promo = await db_session.get(PromoChannel, promo_id)
    if promo:
        await db_session.delete(promo)
        await db_session.commit()
        await callback.answer("✅ Промо-задание успешно удалено!", show_alert=True)
        
    await refresh_settings_panel(callback, db_session, db_user)

# --- FSM СЦЕНАРИЙ: ДОБАВЛЕНИЕ ПРОМО-КАНАЛА ---

@router.callback_query(F.data == "mg_promo_add")
async def process_mg_promo_add_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerSettingsPromo.waiting_for_channel_id)
    
    await callback.message.answer(
        "📢 **Добавление задания [Шаг 1/3]**\n\n"
        "Введите **Telegram ID** канала. Бот должен быть добавлен в этот канал администратором.\n\n"
        "👉 ID должен начинаться с -100 (например: `-100123456789`):",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(ManagerSettingsPromo.waiting_for_channel_id)
async def process_promo_channel_id(message: Message, state: FSMContext):
    text_input = message.text.strip()
    if not text_input.startswith("-100") or not text_input.replace("-", "").isdigit():
        await message.answer("❌ Ошибка! ID канала должен быть числом и начинаться с -100. Попробуйте еще раз:")
        return

    await state.update_data(promo_id=int(text_input))
    await state.set_state(ManagerSettingsPromo.waiting_for_invite_link)
    
    await message.answer(
        "🔗 **Добавление задания [Шаг 2/3]**\n\n"
        "Введите **ссылку-приглашение** на этот канал (её увидят пользователи для перехода):",
        parse_mode="Markdown"
    )

@router.message(ManagerSettingsPromo.waiting_for_invite_link)
async def process_promo_invite_link(message: Message, state: FSMContext):
    text_input = message.text.strip()
    if not text_input.startswith("https://t.me"):
        await message.answer("❌ Ошибка! Ссылка должна начинаться с https://t.me. Попробуйте еще раз:")
        return

    await state.update_data(promo_link=text_input)
    await state.set_state(ManagerSettingsPromo.waiting_for_task_reward)
    
    await message.answer(
        f"💰 **Добавление задания [Шаг 3/3]**\n\n"
        f"Укажите **награду** в валюте {settings.CURRENCY_NAME} за выполнение подписки (целое число):",
        parse_mode="Markdown"
    )

@router.message(ManagerSettingsPromo.waiting_for_task_reward)
async def process_promo_reward(message: Message, state: FSMContext, db_user: User, db_session: AsyncSession):
    text_input = message.text.strip()
    if not text_input.isdigit() or int(text_input) <= 0:
        await message.answer("❌ Ошибка! Награда должна быть целым положительным числом. Попробуйте еще раз:")
        return

    data = await state.get_data()
    channel_id = data.get("promo_id")

    existing = await db_session.get(PromoChannel, channel_id)
    if existing:
        await message.answer("❌ Этот канал уже добавлен в список заданий!")
        await state.clear()
        await refresh_settings_panel(message, db_session, db_user)
        return

    new_promo = PromoChannel(
        id=channel_id,
        invite_link=data.get("promo_link"),
        reward=int(text_input)
    )
    db_session.add(new_promo)
    await db_session.commit()
    await state.clear()

    from bot.keyboards.menu_kb import get_back_to_menu_keyboard
    await message.answer(
        f"🎉 Задание для канала [ID: {channel_id}] успешно создано и активировано!",
        reply_markup=get_back_to_menu_keyboard(to_manager=True)
    )

