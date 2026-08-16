from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.models import ChatConfig, PromoChannel
from bot.keyboards.manager_settings_kb import get_settings_main_keyboard
from bot.states import ManagerSettingsPromo

router = Router(name="manager_settings_router")

async def refresh_settings_panel(message_or_query, session: AsyncSession):
    """Обновляет состояние панели чатов и промо-каналов."""
    # Получаем все чаты, в которых состоит бот
    chats_result = await session.execute(select(ChatConfig).order_by(ChatConfig.title))
    chats = chats_result.scalars().all()

    text = (
        "⚙️ **Настройка чатов и промо-заданий**\n\n"
        "🟢 **Учет активности в группах:**\n"
        "Кликните по кнопке чата ниже, чтобы включить или отключить начисление рейтинга за сообщения в нем.\n\n"
        "📢 **Партнерские каналы:**\n"
        "Вы можете добавить новый канал, подписку на который пользователи должны будут оформить "
        "в разделе '📝 Задания' для получения бонуса."
    )
    
    reply_markup = get_settings_main_keyboard(chats)

    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        try:
            await message_or_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            await message_or_query.answer()


@router.message(F.text == "⚙️ Настройка Чатов и Промо")
async def cmd_manager_settings(message: Message, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    await refresh_settings_panel(message, db_session)


@router.types.CallbackQuery(F.data.startswith("mg_chat_toggle:"))
async def process_mg_chat_toggle(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    chat_id = int(callback.data.split(":")[1])

    chat = await db_session.get(ChatConfig, chat_id)
    if chat:
        # Инвертируем булево значение активности чата
        chat.is_active = not chat.is_active
        await db_session.commit()
        status_text = "включен" if chat.is_active else "выключен"
        await callback.answer(f"ℹ️ Учет активности в чате '{chat.title}' {status_text}!")
    
    await refresh_settings_panel(callback, db_session)


# --- FSM СЦЕНАРИЙ: ДОБАВЛЕНИЕ ПРОМО-КАНАЛА ---

@router.types.CallbackQuery(F.data == "mg_promo_add")
async def process_mg_promo_add_start(callback: CallbackQuery, is_manager: bool, state: FSMContext):
    if not is_manager: return
    await state.set_state(ManagerSettingsPromo.waiting_for_channel_id)
    
    await callback.message.answer(
        "📢 **Добавление задания [Шаг 1/3]**\n\n"
        "Введите **Telegram ID** канала. Бот должен быть добавлен в этот канал в качестве администратора "
        "(с правами проверки участников).\n\n"
        "👉 ID должен начинаться с -100 (например: `-100123456789`):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ManagerSettingsPromo.waiting_for_channel_id)
async def process_promo_channel_id(message: Message, state: FSMContext):
    text_input = message.text.strip()
    
    # Валидация формата ID
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
async def process_promo_reward(message: Message, state: FSMContext, db_session: AsyncSession):
    text_input = message.text.strip()
    
    if not text_input.isdigit() or int(text_input) <= 0:
        await message.answer("❌ Ошибка! Награда должна быть целым положительным числом. Попробуйте еще раз:")
        return

    data = await state.get_data()
    channel_id = data.get("promo_id")

    # Проверяем, нет ли уже такого канала в базе
    existing = await db_session.get(PromoChannel, channel_id)
    if existing:
        await message.answer("❌ Этот канал уже добавлен в список заданий!")
        await state.clear()
        await refresh_settings_panel(message, db_session)
        return

    # Сохраняем в PostgreSQL
    new_promo = PromoChannel(
        id=channel_id,
        invite_link=data.get("promo_link"),
        reward=int(text_input)
    )
    db_session.add(new_promo)
    await db_session.commit()
    await state.clear()

    await message.answer(f"🎉 Задание для канала [ID: {channel_id}] успешно создано и активировано!")
    await refresh_settings_panel(message, db_session)

@router.types.CallbackQuery(F.data.startswith("mg_promo_del:"))
async def process_mg_promo_del(callback: CallbackQuery, is_manager: bool, db_session: AsyncSession):
    if not is_manager: return
    promo_id = int(callback.data.split(":"))
    promo = await db_session.get(PromoChannel, promo_id)
    if promo:
        await db_session.delete(promo)
        await db_session.commit()
        await callback.answer("✅ Промо-задание успешно удалено!", show_alert=True)
    await refresh_settings_panel(callback, db_session)
