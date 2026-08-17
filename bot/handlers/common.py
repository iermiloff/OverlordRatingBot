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

stats_cooldowns = {}
COOLDOWN_SECONDS = 600  # 10 минут защиты от спама

# --- КОМАНДА /start СТРОГО В ЛИЧКЕ БОТА (ЗАЩИТА ЧАТА ОТ КАШИ) ---

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
    """Бесшовный возврат пользователя в главное меню (с фото-защитой)."""
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

# --- ГРУППОВАЯ КОМАНДА /stats С АДАПТИВНОЙ ГЕЙМИФИКАЦИЕЙ ---

@router.message(Command("stats"), F.chat.type.in_(["group", "supergroup"]))
async def cmd_group_stats(message: Message, db_user: User, db_session: AsyncSession):
    """Выводит карточку активности. Текущий титул несгораемый, но прогресс штрафуется за траты."""
    user_id = message.from_user.id
    current_time = time.time()

    if user_id not in settings.managers_list:
        if user_id in stats_cooldowns:
            last_call = stats_cooldowns[user_id]
            time_passed = current_time - last_call
            if time_passed < COOLDOWN_SECONDS:
                remaining_minutes = int((COOLDOWN_SECONDS - time_passed) // 60)
                remaining_seconds = int((COOLDOWN_SECONDS - time_passed) % 60)
                warn_msg = await message.reply(
                    f"⏱️ **Анти-флуд защита чата!**\n"
                    f"Вы можете запрашивать статистику раз в 10 минут.\n"
                    f"⏳ Подождите еще: **{remaining_minutes} мин. {remaining_seconds} сек.**"
                )
                try:
                    time.sleep(5)
                    await warn_msg.delete()
                    await message.delete()
                except Exception: pass
                return

    stats_cooldowns[user_id] = current_time

    # Считаем общее количество текстовых сообщений пользователя в логах активности
    msg_count_q = select(func.count(ActivityLog.id)).where(
        and_(
            ActivityLog.user_id == db_user.tg_id,
            ActivityLog.message_length > 0
        )
    )
    total_messages = (await db_session.execute(msg_count_q)).scalar() or 0

    # Разворачиваем конфигурацию титулов проекта
    titles = settings.parsed_titles
    sorted_titles = sorted(titles.values(), key=lambda x: x.min_rating)

    # 1. ТЕКУЩИЙ ТИТУЛ: Считается по несгораемому историческому максимуму (lifetime_rating)
    current_title_name = "Новичок"
    current_title_id = 1
    for t in sorted_titles:
        if db_user.lifetime_rating >= t.min_rating:
            current_title_name = t.name
            current_title_id = t.id

    # 2. ПРОГРЕСС ДО СЛЕДУЮЩЕГО ТИТУЛА: Считается от актуального кошелька (current_rating)
    next_title_name = "Максимум"
    next_title_required_rating = 0
    has_next = False

    # Ищем следующий титул по цепочке за текущим достигнутым
    for t in sorted_titles:
        if t.id > current_title_id:
            next_title_name = t.name
            next_title_required_rating = t.min_rating
            has_next = True
            break

    # Формируем строку прогресса
    if has_next:
        # Сколько осталось добрать от текущего кошелька
        if db_user.current_rating >= next_title_required_rating:
            # Если из-за хитрых начислений кошелек уже выше, но lifetime еще не догнал по ID
            remains_text = f"✨ Доступно получение титула **'{next_title_name}'** при следующем начислении опыта!"
        else:
            needed = next_title_required_rating - db_user.current_rating
            remains_text = f"🎯 До титула **'{next_title_name}'** осталось накопить: **{needed}** {settings.CURRENCY_NAME}"
    else:
        remains_text = "👑 Вы достигли вершины карьерной лестницы чата!"

    # Компактный и стильный текст карточки для группы (Маркдаун заменен на HTML для стабильности)
    stats_text = (
        f"📊 <b>Игровая статистика участника</b>\n\n"
        f"👤 Пользователь: {message.from_user.mention_html()}\n"
        f"🎖️ Текущий Ранг: <b>{current_title_name}</b> <i>(несгораемый)</i>\n\n"
        f"💬 Отправлено сообщений: <b>{total_messages}</b> шт.\n"
        f"💰 Доступный баланс: <b>{db_user.current_rating}</b> {settings.CURRENCY_NAME}\n"
        f"💎 Исторический опыт: <b>{db_user.lifetime_rating}</b> XP\n\n"
        f"🧭 <u>Экономический путь:</u>\n{remains_text}"
    )

    await message.answer(stats_text, parse_mode="HTML")

