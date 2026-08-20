import time
import random  # СЮДА: Подключаем рандом для админской пасхалки
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from config import settings
from database.models import ChatConfig, PromoChannel, User, ActivityLog
from bot.keyboards.menu_kb import get_user_inline_menu, get_manager_inline_menu

router = Router(name="common_router")

stats_cooldowns = {}
COOLDOWN_SECONDS = 600  # 10 минут кулдауна для игроков

@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, db_user: User, state: FSMContext):
    """Приветственный хэндлер с принудительным удалением репли-клавиатуры."""
    await state.clear()
    
    await message.answer(
        "🧹 Старая текстовая клавиатура отключена. Переходим на интерактивное меню!",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Твой оригинальный код вывода инлайн-меню:
    if message.from_user.id in settings.managers_list:
        await message.answer(
            " Вы вошли как менеджер системы!", 
            reply_markup=get_manager_inline_menu()
        )
    else:
        text = (
            f" **Добро пожаловать в Личный Кабинет {settings.BOT_NAME}!**\n\n"
            f"Здесь ты можешь отслеживать свою статистику активности в чатах."
        )
        await message.answer(text, reply_markup=get_user_inline_menu(), parse_mode="Markdown")

@router.callback_query(F.data == "main_menu_user")
async def back_to_user_menu(callback: CallbackQuery):
    """Бесшовный возврат пользователя в главное меню."""
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

# --- ГРУППОВАЯ КОМАНДА /stats С АДМИНСКОЙ ПАСХАЛКОЙ И КОНТРОЛЕМ ЛИМИТОВ ---

@router.message(Command("stats"), F.chat.type.in_(["group", "supergroup"]))
async def cmd_group_stats(message: Message, db_user: User, db_session: AsyncSession):
    """Выводит карточку активности. Для менеджеров активирует шуточную пасхалку."""
    user_id = message.from_user.id
    current_time = time.time()

    # ПАСХАЛКА: Если команду вызвал Оверлорд/Менеджер системы
    if user_id in settings.managers_list:
        # Генерируем сочные рандомные показатели админских будней
        coffee_liters = round(random.uniform(4.5, 42.8), 1)
        sleepless_nights = random.randint(3, 14)
        unfair_bans = random.randint(150, 890)
        profile_views = random.randint(2400, 13500)
        nerve_cells = random.randint(1, 4)

        manager_easter_egg = (
            f"👑 <b>СЕКРЕТНЫЙ CRM-ПРОФИЛЬ</b> 👑\n\n"
            f"👤 Администратор: {message.from_user.mention_html()}\n"
            f"⚙️ Ранг доступа: <code>Root / System Manager</code>\n\n"
            f"☕ Выпито кофе на смене: <b>{coffee_liters} л.</b>\n"
            f"🌙 Ночей без сна подряд: <b>{sleepless_nights}</b> шт.\n"
            f"👁️ Просмотрено профилей абузеров: <b>{profile_views}</b> раз\n"
            f"🔨 Несправедливо выданных банов: <b>{unfair_bans}</b> юзеров\n\n"
            f"📋 <u>Статус ЦНС:</u> Осталось <b>{nerve_cells} нервные клетки</b>. "
            f"Рекомендуется экстренно закрыть бота и обнять кота! 🐱"
        )
        await message.answer(manager_easter_egg, parse_mode="HTML")
        return

    # --- ЛОГИКА ДЛЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ (КУЛДАУН 10 МИНУТ) ---
    if user_id in stats_cooldowns:
        last_call = stats_cooldowns[user_id]
        time_passed = current_time - last_call
        if time_passed < COOLDOWN_SECONDS:
            remaining_minutes = int((COOLDOWN_SECONDS - time_passed) // 60)
            remaining_seconds = int((COOLDOWN_SECONDS - time_passed) % 60)
            warn_msg = await message.reply(
                f"⏱️ <b>Анти-флуд защита чата!</b>\n"
                f"Вы можете запрашивать статистику раз в 10 минут.\n"
                f"⏳ Подождите еще: <b>{remaining_minutes} мин. {remaining_seconds} сек.</b>"
            )
            try:
                time.sleep(5)
                await warn_msg.delete()
                await message.delete()
            except Exception: pass
            return

    stats_cooldowns[user_id] = current_time

    # --- ПРОДОЛЖЕНИЕ ЛОГИКИ ДЛЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ ---
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
    current_title_min = 0
    for t in sorted_titles:
        if db_user.lifetime_rating >= t.min_rating:
            current_title_name = t.name
            current_title_id = t.id
            current_title_min = t.min_rating

    # 2. ПРОГРЕСС ДО СЛЕДУЮЩЕГО ТИТУЛА: Считается от актуального кошелька (current_rating)
    next_title_name = "Максимум"
    next_title_required_rating = 0
    has_next = False

    for t in sorted_titles:
        if t.id > current_title_id:
            next_title_name = t.name
            next_title_required_rating = t.min_rating
            has_next = True
            break

    # Формируем строку прогресса
    if has_next:
        if db_user.current_rating >= next_title_required_rating:
            remains_text = f"✨ Доступно получение титула <b>'{next_title_name}'</b> при следующем начислении опыта!"
        else:
            needed = next_title_required_rating - db_user.current_rating
            remains_text = f"🎯 До титула <b>'{next_title_name}'</b> осталось накопить: <b>{needed}</b> {settings.CURRENCY_NAME}"
    else:
        remains_text = "👑 Вы достигли вершины карьерной лестницы чата!"

    # Компактный и стильный текст карточки для группы
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

