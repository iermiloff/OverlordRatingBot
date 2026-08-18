import logging
import random
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_, delete

from config import settings
from database.connection import AsyncSessionLocal
from database.models import (
    Giveaway, User, ChatConfig, 
    ShopItem, Inventory, Order, OrderStatus
)

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# Переменная в памяти для времени следующего сундука
next_chest_spawn_time = None

async def calculate_next_chest_time():
    """Расчет времени следующего сундука на основе МИНУТ из админки."""
    global next_chest_spawn_time
    now = datetime.utcnow()
    
    async with AsyncSessionLocal() as session:
        # Вытягиваем конфигурацию первой активной группы для получения настроек
        cfg_q = select(ChatConfig).where(ChatConfig.is_active == True).limit(1)
        cfg_res = await session.execute(cfg_q)
        cfg = cfg_res.scalar_one_or_none()
        
        # Если в админке еще ничего не настроено, берем безопасный дефолт в минутах
        min_sleep_min = cfg.chest_min_sleep_minutes if cfg and hasattr(cfg, "chest_min_sleep_minutes") else 15
        random_win_min = cfg.chest_random_window_minutes if cfg and hasattr(cfg, "chest_random_window_minutes") else 30
    
    random_minutes = random.randint(0, random_win_min)
    delay = timedelta(minutes=min_sleep_min + random_minutes)
    
    next_chest_spawn_time = now + delay
    logger.info(
        f"📦 [ТАЙМЕР СУНДУКОВ] Следующий дроп по админ-настройкам: "
        f"{next_chest_spawn_time.strftime('%d.%m.%Y %H:%M:%S')} UTC"
    )

async def check_and_send_random_chests(bot):
    """Ежеминутная проверка таймера и выброс сундуков в чаты."""
    global next_chest_spawn_time
    now = datetime.utcnow()
    
    if next_chest_spawn_time is None:
        await calculate_next_chest_time()
        return

    if now >= next_chest_spawn_time:
        logger.info("📦 Время пришло! Выбрасываем Секретные Сундуки...")
        
        async with AsyncSessionLocal() as session:
            chats_q = select(ChatConfig).where(ChatConfig.is_active == True)
            chats = (await session.execute(chats_q)).scalars().all()
            
            if not chats:
                logger.warning("📦 Сундук готов, но активных чатов в БД нет!")
                await calculate_next_chest_time()
                return

            chest_text = (
                "📦 **НАЙДЕН СЕКРЕТНЫЙ СУНДУК АКТИВНОСТИ!** 📦\n\n"
                "Оверлорды сбросили на поле боя сундук со случайными сокровищами! "
                "Кто первый успеет нажать на кнопку ниже и применить свой Ключ "
                "— заберет всю добычу себе!\n\n"
                "🔋 _Требования и цена открытия зависят от настроек пула админки._"
            )
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            chest_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Открыть Сундук!", 
                                      callback_data="chest_claim_click")]
            ])

            for chat in chats:
                try:
                    await bot.send_message(
                        chat_id=chat.id, 
                        text=chest_text, 
                        reply_markup=chest_kb, 
                        parse_mode="Markdown"
                    )
                    logger.info(f"✅ Сундук отправлен в чат [{chat.title}]")
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки в чат {chat.id}: {e}")
            
        await calculate_next_chest_time()

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
            title_id = int(parts[0])
            ticket_id = int(parts[1])
            
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
                    f"2. 🔓 Участие **БЕСПЛАТНОЕ**, лотерейные билеты не требуются!"
                )
                footer_text = (
                    "ℹ️ _Вам не нужно никуда нажимать! Бот автоматически "
                    "просканирует чат и выберет победителей среди тех, кто "
                    "подходит по критериям!_"
                )
            else:
                ticket_item = await session.get(ShopItem, ticket_id)
                ticket_name = ticket_item.name if ticket_item else "Удаленный билет"
                cond_text = (
                    f"1. 🎖️ Наличие титула от **'{t_name}'** и выше.\n"
                    f"2. 🎟️ Наличие билета **'{ticket_name}'** в вашем инвентаре."
                )
                footer_text = (
                    f"📈 _Покупайте билеты в '🛍️ Магазин товаров'! Каждый билет "
                    f"пропорционально умножает ваши шансы в лотерейном барабане бота!_\n\n"
                    f"⚠️ **ВНИМАНИЕ:** В случае победы у счастливчика "
                    f"**сгорают ВСЕ билеты данного типа**, обнуляя его шансы "
                    f"для следующего раунда! У проигравших билеты сохраняются! 🎇"
                )

            chats = (await session.execute(
                select(ChatConfig).where(ChatConfig.is_active == True)
            )).scalars().all()
            
            text_announce = (
                "🎉 **ВНИМАНИЕ! ЗАПЛАНИРОВАН АВТОМАТИЧЕСКИЙ РОЗЫГРЫШ!** 🎉\n\n"
                f"🎁 **Приз лотереи:** {prize_currency}\n"
                f"🏆 **Призовых мест:** {ga.winners_count}\n"
                f"⏳ **Авто-финал состоится:** `{ga.finalize_at.strftime('%d.%m.%Y %H:%M')}`\n\n"
                f"🔒 **КРИТЕРИИ АВТО-ОТБОРА УЧАСТНИКОВ:**\n{cond_text}\n\n"
                f"{footer_text}"
            )
            
            for chat in chats:
                try: 
                    await bot.send_message(
                        chat_id=chat.id, 
                        text=text_announce, 
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
            title_id = int(parts[0])
            ticket_id = int(parts[1])
            
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
                else:
                    new_order = Order(
                        user_id=w.tg_id, 
                        source="giveaway", 
                        item_name=f"[РОЗЫГРЫШ] {ga.reward_value}",
                        status=OrderStatus.CREATED.value, 
                        delivery_data="Выиграно автоматически. Ждите менеджера."
                    )
                    session.add(new_order)
                    
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
                    "Победители полностью обнулили свои билеты! "
                    "У остальных купоны сохранены! 🔥"
                )
            else:
                footer_status_text = "Награды зачислены в личные кабинеты! 👏"

            chats = (await session.execute(
                select(ChatConfig).where(ChatConfig.is_active == True)
            )).scalars().all()
            winners_str = "\n".join(mentions)
            text_results = (
                "🎉 **АВТОМАТИЧЕСКИЙ РОЗЫГРЫШ ЗАВЕРШЕН!** 🎉\n\n"
                f"🎁 **Разыгранный приз:** {prize_currency}\n"
                f"🏆 **Список наших счастливых победителей:**\n{winners_str}\n\n"
                f"Поздравляем счастливчиков! {footer_status_text}"
            )
            for chat in chats:
                try: 
                    await bot.send_message(
                        chat_id=chat.id, 
                        text=text_results, 
                        parse_mode="Markdown"
                    )
                except Exception: pass
                
            ga.status = "finished"
            
        await session.commit()

def start_scheduler(bot):
    """Запуск фонового планировщика внутри главного процесса asyncio."""
    import asyncio
    scheduler.add_job(check_and_process_giveaways, 'interval', minutes=1, args=[bot])
    scheduler.add_job(check_and_send_random_chests, 'interval', minutes=1, args=[bot])
    
    # Асинхронно вычисляем первое время спавна, чтобы не блокировать синхронный поток
    asyncio.create_task(calculate_next_chest_time())
    
    scheduler.start()
    logger.info("⏰ Фоновый планировщик успешно запущен!")

