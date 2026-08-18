import logging
import random
import asyncio
from datetime import datetime
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, and_

from config import settings
from database.connection import AsyncSessionLocal
from database.models import (
    Giveaway, User, ChatConfig, 
    ShopItem, StockUnit, SystemSettings
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Время последнего успешного дропа сундука в чаты (кэшируем только факт отправки)
last_chest_drop_time = None

async def check_and_send_random_chests(bot):
    """Ежеминутный динамический воркер контроля и спавна сундуков."""
    global last_chest_drop_time
    now = datetime.utcnow()
    
    async with AsyncSessionLocal() as session:
        # 1. Всегда вытягиваем СВЕЖИЕ минуты из админки (SystemSettings id=1)
        res = await session.execute(
            select(SystemSettings).where(SystemSettings.id == 1)
        )
        sys_settings = res.scalar_one_or_none()
        
        # Если настроек еще нет в БД, ставим безопасный дефолт в минутах
        min_sleep = (
            sys_settings.chest_quiet_hours 
            if sys_settings else 15
        )
        random_win = (
            sys_settings.chest_random_hours 
            if sys_settings else 30
        )
        
        # Иннициализируем точку отсчета при самом первом запуске бота
        if last_chest_drop_time is None:
            last_chest_drop_time = now - timedelta(minutes=min_sleep)
            logger.info("⏱️ [СУНДУКИ] Инициализация стартовой метки времени.")
            return

        # Рассчитываем, сколько минут прошло с момента последнего дропа
        minutes_passed = (now - last_chest_drop_time).total_seconds() / 60.0
        
        # Если время сна еще не вышло — сундук строго спит
        if minutes_passed < min_sleep:
            return

        # Математическое окно рандома: бросаем кубик каждую минуту!
        # Шанс выпадения в текущую минуту внутри окна разброса
        current_window_size = random_win if random_win > 0 else 1
        spawn_chance = 1.0 / current_window_size
        
        # Дополнительный предохранитель: если перешагнули максимальный лимит, дропаем 100%
        max_total_wait = min_sleep + random_win
        force_drop = minutes_passed >= max_total_wait
        
        if force_drop or (random.random() < spawn_chance):
            logger.info("📦 [ДРОП] Динамический таймер сработал! Отправляем...")
            
            chats_q = select(ChatConfig).where(ChatConfig.is_active == True)
            chats = (await session.execute(chats_q)).scalars().all()
            
            if not chats:
                logger.warning("📦 Сундук готов, но активных чатов нет!")
                last_chest_drop_time = now # Сдвигаем метку, чтобы не спамить
                return

            chest_text = (
                "📦 **НАЙДЕН СЕКРЕТНЫЙ СУНДУК АКТИВНОСТИ!** 📦\n\n"
                "Оверлорды сбросили на поле боя сундук со случайными сокровищами! "
                "Кто первый успеет нажать на кнопку ниже — заберет добычу!"
            )
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            chest_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Открыть Сундук!", 
                                      callback_data="chest_open_click")]
            ])

            for chat in chats:
                try:
                    await bot.send_message(
                        chat_id=chat.id, text=chest_text, 
                        reply_markup=chest_kb, parse_mode="Markdown"
                    )
                    logger.info(f"✅ Сундук успешно отправлен в чат {chat.title}")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки в чат {chat.id}: {e}")
            
            # Фиксируем время УСПЕШНОГО дропа для следующего цикла
            last_chest_drop_time = now

async def check_and_process_giveaways(bot):
    """Каждоминутный фоновый воркер для проверки автоматических лотерей."""
    now = datetime.utcnow()
    
    async with AsyncSessionLocal() as session:
        # 1. СЕКЦИЯ АВТО-АНОНСОВ
        announce_q = select(Giveaway).where(
            and_(Giveaway.status == "created", Giveaway.announce_at <= now)
        )
        to_announce = (await session.execute(announce_q)).scalars().all()
        
        for ga in to_announce:
            parts = str(ga.condition_value).split(":")
            title_id = int(parts)
            ticket_id = int(parts)
            
            t_name = settings.parsed_titles.get(title_id).name
            
            is_rating_prize = (
                ga.reward_type == "rating" or 
                str(ga.reward_value).strip().isdigit()
            )
            if is_rating_prize:
                prize_currency = (
                    f"{settings.CURRENCY_EMOJI} {ga.reward_value} "
                    f"{settings.CURRENCY_NAME}"
                )
            else:
                prize_currency = f"🎒 {ga.reward_value}"

            if ticket_id == 0:
                cond_text = (
                    f"1. 🎖️ Наличие титула от **'{t_name}'** и выше.\n"
                    f"2. 🔓 Участие **БЕСПЛАТНОЕ**, билеты не требуются!"
                )
                footer_text = (
                    "ℹ️ _Бот автоматически выберет победителей среди тех, "
                    "кто подходит по критериям активности!_"
                )
            else:
                ticket_item = await session.get(ShopItem, ticket_id)
                ticket_name = ticket_item.name if ticket_item else "Билет"
                cond_text = (
                    f"1. 🎖️ Наличие титула от **'{t_name}'** и выше.\n"
                    f"2. 🎟️ Наличие билета **'{ticket_name}'** в инвентаре."
                )
                footer_text = (
                    f"⚠️ **ВНИМАНИЕ:** В случае победы у счастливчика "
                    f"**сгорают ВСЕ билеты данного типа**! 🎇"
                )

            chats = (await session.execute(
                select(ChatConfig).where(ChatConfig.is_active == True)
            )).scalars().all()
            
            text_announce = (
                "🎉 **ЗАПЛАНИРОВАН АВТОМАТИЧЕСКИЙ РОЗЫГРЫШ!** 🎉\n\n"
                f"🎁 **Приз лотереи:** {prize_currency}\n"
                f"🏆 **Призовых мест:** {ga.winners_count}\n"
                f"⏳ **Авто-финал:** `{ga.finalize_at.strftime('%d.%m.%Y %H:%M')}`\n\n"
                f"🔒 **КРИТЕРИИ АВТО-ОТБОРА:**\n{cond_text}\n\n"
                f"{footer_text}"
            )
            
            for chat in chats:
                try: 
                    await bot.send_message(
                        chat_id=chat.id, text=text_announce, 
                        parse_mode="Markdown"
                    )
                except Exception: pass
                
            ga.status = "announced"
        
        # 2. СЕКЦИЯ АВТО-ФИНАЛОВ
        finalize_q = select(Giveaway).where(
            and_(Giveaway.status == "announced", Giveaway.finalize_at <= now)
        )
        to_finalize = (await session.execute(finalize_q)).scalars().all()
        
        for ga in to_finalize:
            parts = str(ga.condition_value).split(":")
            title_id = int(parts)
            ticket_id = int(parts)
            
            min_rating = settings.parsed_titles.get(title_id).min_rating
            
            is_rating_prize = (
                ga.reward_type == "rating" or 
                str(ga.reward_value).strip().isdigit()
            )
            if is_rating_prize:
                prize_currency = (
                    f"{settings.CURRENCY_EMOJI} {ga.reward_value} "
                    f"{settings.CURRENCY_NAME}"
                )
            else:
                prize_currency = f"🎒 *{ga.reward_value}*"

            if ticket_id == 0:
                users_q = select(User).where(and_(
                    User.lifetime_rating >= min_rating, 
                    User.is_banned == False,
                    User.tg_id.not_in(settings.managers_list)
                ))
                query_res = await session.execute(users_q)
                eligible_records = [(u, 1) for u in query_res.scalars().all()]
            else:
                users_q = select(User, Inventory.quantity).join(
                    Inventory, Inventory.user_id == User.tg_id
                ).where(and_(
                    User.lifetime_rating >= min_rating, 
                    Inventory.item_id == ticket_id, 
                    Inventory.quantity >= 1, 
                    User.is_banned == False,
                    User.tg_id.not_in(settings.managers_list)
                ))
                eligible_records = (await session.execute(users_q)).all()

            if not eligible_records:
                ga.status = "finished"
                continue

            wheel = []
            user_ticket_map = {}
            for user_obj, qty in eligible_records:
                user_ticket_map[user_obj.tg_id] = qty
                for _ in range(qty): 
                    wheel.append(user_obj)

            winners = []
            actual_winners_count = min(len(eligible_records), ga.winners_count)
            while len(winners) < actual_winners_count and wheel:
                chosen = random.choice(wheel)
                if chosen not in winners: 
                    winners.append(chosen)
                wheel = [u for u in wheel if u.tg_id != chosen.tg_id]

            mentions = []
            winner_ids = [w.tg_id for w in winners]

            for w in winners:
                if is_rating_prize:
                    w.current_rating += int(ga.reward_value)
                    w.lifetime_rating += int(ga.reward_value)
                    try:
                        await bot.send_message(
                            chat_id=w.tg_id,
                            text=f"🎉 **Поздравляем с победой!** 🎉\n\n"
                                 f"🎁 Вы выиграли: **{ga.reward_value} "
                                 f"{settings.CURRENCY_NAME}**!",
                            parse_mode="Markdown"
                        )
                    except Exception: pass
                else:
                    new_order = Order(
                        user_id=w.tg_id, source="giveaway", 
                        item_name=f"[РОЗЫГРЫШ] {ga.reward_value}", 
                        status=OrderStatus.CREATED.value, 
                        delivery_data="Выиграно автоматически."
                    )
                    session.add(new_order)
                    try:
                        await bot.send_message(
                            chat_id=w.tg_id,
                            text=f"🎒 **Поздравляем с победой!** 🎒\n\n"
                                 f"Вы выиграли реальный мерч: **{ga.reward_value}**!\n"
                                 f"Заполните контакты в '🎁 Мои Награды'.",
                            parse_mode="Markdown"
                        )
                    except Exception: pass
                    
                    for manager_id in settings.managers_list:
                        try:
                            await bot.send_message(
                                chat_id=manager_id,
                                text=f"🎁 **Розыгрыш завершен!**\n\n"
                                     f"👤 Победитель: @{w.username or w.tg_id}\n"
                                     f"🎒 Награда: *{ga.reward_value}*",
                                parse_mode="Markdown"
                            )
                        except Exception: pass
                
                qty_label = (
                    f" _(заявил {user_ticket_map[w.tg_id]} шт. билетов)_" 
                    if ticket_id > 0 else ""
                )
                mentions.append(f"👑 @{w.username or w.full_name}{qty_label}")

            if ticket_id > 0 and winner_ids:
                burn_query = delete(Inventory).where(and_(
                    Inventory.item_id == ticket_id,
                    Inventory.user_id.in_(winner_ids)
                ))
                await session.execute(burn_query)
                footer_status_text = (
                    "Победители обнулили свои билеты! "
                    "У остальных купоны сохранены! 🔥"
                )
            else:
                footer_status_text = "Награды зачислены в кабинеты! 👏"

            chats = (await session.execute(
                select(ChatConfig).where(ChatConfig.is_active == True)
            )).scalars().all()
            winners_str = "\n".join(mentions)
            text_results = (
                "🎉 **АВТОМАТИЧЕСКИЙ РОЗЫГРЫШ ЗАВЕРШЕН!** 🎉\n\n"
                f"🎁 **Разыгранный приз:** {prize_currency}\n"
                f"🏆 **Список победителей:**\n{winners_str}\n\n"
                f"Поздравляем счастливчиков! {footer_status_text}"
            )
            for chat in chats:
                try: 
                    await bot.send_message(
                        chat_id=chat.id, text=text_results, 
                        parse_mode="Markdown"
                    )
                except Exception: pass
                
            ga.status = "finished"
            
        await session.commit()

def start_scheduler(bot):
    """Запуск фонового планировщика внутри главного процесса asyncio."""
    scheduler.add_job(check_and_process_giveaways, 'interval', minutes=1, args=[bot])
    scheduler.add_job(check_and_send_random_chests, 'interval', minutes=1, args=[bot])
    scheduler.start()
    logger.info("⏰ Фоновый планировщик успешно запущен в работу!")

