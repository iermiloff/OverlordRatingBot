import time
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import ChatConfig, PromoChannel, User, ActivityLog
from bot.keyboards.menu_kb import get_user_inline_menu, get_manager_inline_menu

router = Router(name="common_router")

# Локальный кэш для защиты от спама: {user_id: timestamp_последнего_вызова}
stats_cooldowns = {}
COOLDOWN_SECONDS = 600  # 10 минут = 600 секунд

# --- КОМАНДА /start СТРОГО В ЛИЧКЕ БОТА (ЗАЗАЩИТА ЧАТА ОТ КАШИ) ---

@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, db_user: User):
    """Приветственный хэндлер при команде /start в личных сообщениях."""
    text = (
        f"🤖 **Добро пожаловать в Личный Кабинет {settings.BOT_NAME}!**\n\n"
        f"Здесь ты можешь отслеживать свою статистику активности в чатах, "
        f"проверять текущий ранг, выполнять партнерские задания и обменивать "
        f"накопленный рейтинг на реальный мерч в нашем магазине! 🛍️\n\n"
        f"Выбери нужный раздел на панели ниже:"
    )
    
    if message.from_user.id in settings.managers_list:
        await message.answer(
            f"👑 **Вы вошли как менеджер системы!**\n\nВам доступен расширенный пульт CRM управления экономикой чатов:", 
            reply_markup=get_manager_inline_menu()
        )
    else:
        await message.answer(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")


@router.callback_query(F.data == "main_menu_user")
async def back_to_user_menu(callback: CallbackQuery):
    """Бесшовный возврат пользователя в главное меню (с защитой от фото-карточек)."""
    text = f"🤖 **Главное меню личного кабинета:**\n\nВыбери интересующий тебя раздел экономики:"
    
    if callback.message.photo or callback.message.animation:
        await callback.message.answer(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")
        try: await callback.message.delete()
        except Exception: pass
    else:
        try: await callback.message.edit_text(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")
        except Exception: await callback.message.answer(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "main_menu_manager")
async def back_to_manager_menu(callback: CallbackQuery, is_manager: bool):
    """Бесшовный возврат менеджера в главное меню админки."""
    if not is_manager: return
        
    text = f"👑 **Главное меню панели управления CRM:**"
    
    if callback.message.photo or callback.message.animation:
        await callback.message.answer(text, reply_markup=get_manager_inline_menu())
        try: await callback.message.delete()
        except Exception: pass
    else:
        try: await callback.message.edit_text(text, reply_markup=get_manager_inline_menu())
        except Exception: await callback.message.answer(text, reply_markup=get_manager_inline_menu())
    await callback.answer()


# --- ГРУППОВАЯ КОМАНДА /stats С КОНТРОЛЕМ ЛИМИТОВ (COOLDOWN) ---

@router.message(Command("stats"), F.chat.type.in_(["group", "supergroup"]))
async def cmd_group_stats(message: Message, db_user: User, db_session: AsyncSession):
    """Выводит компактную карточку активности пользователя прямо в групповой чат с лимитом 10 минут."""
    user_id = message.from_user.id
    current_time = time.time()

    # ИСКЛЮЧЕНИЕ: Менеджеры могут вызывать команду без ограничений по времени
    if user_id not in settings.managers_list:
        if user_id in stats_cooldowns:
            last_call = stats_cooldowns[user_id]
            time_passed = current_time - last_call

            if time_passed < COOLDOWN_SECONDS:
                remaining_minutes = int((COOLDOWN_SECONDS - time_passed) // 60)
                remaining_seconds = int((COOLDOWN_SECONDS - time_passed) % 60)
                
                # Мягкое предупреждение: отвечаем реплаем и удаляем его через 5 секунд, чтобы не спамить в чат
                warn_msg = await message.reply(
                    f"⏱️ **Анти-флуд защита чата!**\n"
                    f"Вы можете запрашивать статистику раз в 10 минут.\n"
                    f"⏳ Подождите еще: **{remaining_minutes} мин. {remaining_seconds} сек.**"
                )
                try:
                    time.sleep(5) # Короткая пауза для прочтения
                    await warn_msg.delete()
                    await message.delete() # Удаляем и само сообщение пользователя, чтобы очистить чат
                except Exception: pass
                return

    # Записываем текущее время вызова в кэш
    stats_cooldowns[user_id] = current_time

    # Считаем общее количество текстовых сообщений пользователя в логах активности
    msg_count_q = select(func.count(ActivityLog.id)).where(
        and_(
            ActivityLog.user_id == db_user.tg_id,
            ActivityLog.message_length > 0
        )
    )
    total_messages = (await db_session.execute(msg_count_q)).scalar() or 0

    # Автоматически вычисляем текущий Титул пользователя на основе его lifetime_rating
    titles = settings.parsed_titles
    current_title_name = "Новичок"
    
    for t in sorted(titles.values(), key=lambda x: x.min_rating, reverse=True):
        if db_user.lifetime_rating >= t.min_rating:
            current_title_name = t.name
            break

    # Компактный и стильный текст карточки для группы
    stats_text = (
        f"📊 **Игровая статистика участника**\n\n"
        f"👤 Пользователь: {message.from_user.mention_html()}\n"
        f"🎖️ Текущий Титул: **{current_title_name}**\n\n"
        f"💬 Отправлено сообщений: **{total_messages}** шт.\n"
        f"💰 Доступный баланс: **{db_user.current_rating}** {settings.CURRENCY_NAME}\n"
        f"💎 Всего накоплено опыта: **{db_user.lifetime_rating}** XP"
    )

    await message.answer(stats_text, parse_mode="HTML")
