import logging
import random
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_, func, update

from config import settings
from database.connection import AsyncSessionLocal
from database.models import (
    Giveaway, User, ChatConfig, 
    ShopItem, StockUnit, SystemSettings, ActivityLog
)

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def get_sys_settings(session) -> SystemSettings:
    """Безопасное извлечение настроек сундука."""
    res = await session.execute(
        select(SystemSettings).where(SystemSettings.id == 1)
    )
    s = res.scalar_one_or_none()
    if not s:
        s = SystemSettings(id=1)
        session.add(s)
        await session.commit()
    return s

# --- 🎁 МОДУЛЬ 1: АВТОМАТИЧЕСКИЙ ЗАБРОС СУНДУКОВ В ЧАТЫ ---

async def check_and_send_random_chests(bot: Bot):
    """Каждую минуту проверяет тайм-лимиты и бросает сундук в активные чаты."""
    async with AsyncSessionLocal() as session:
        s = await get_sys_settings(session)
        now = datetime.utcnow()
        
        # Вычисляем окно тишины на основе No-Code настроек минут
        min_sleep = s.chest_quiet_hours
        max_sleep = s.chest_quiet_hours + s.chest_random_hours
        
        # Проверяем, когда был последний заброс сундука по логам
        last_log_q = select(ActivityLog).where(
            ActivityLog.earned_rating == 0 # Условный маркер сундука в логе
        ).order_by(ActivityLog.created_at.desc()).limit(1)
        last_drop = (await session.execute(last_log_q)).scalar_one_or_none()
        
        if last_drop:
            diff = (now - last_drop.created_at).total_seconds() / 60.0
            if diff < min_sleep: return # Сундук еще «спит» гарантированные минуты
            if diff < max_sleep and random.random() > 0.15: return # Рандомный шанс
            
        # Извлекаем чаты, разделяя платформы для кроссплатформенного шлюза
        chats_q = select(ChatConfig).where(ChatConfig.is_active == True)
        active_chats = (await session.execute(chats_q)).scalars().all()
        
        if not active_chats: return
        
        chest_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Открыть сундук!", callback_data="chest_open_click")]
        ])
        
        for chat in active_chats:
            if chat.platform == "tg":
                # Шлюз Telegram: отправляем интерактивный сундук
                try:
                    msg = await bot.send_message(
                        chat_id=chat.id,
                        text="📦 **В ЧАТЕ ОБНАРУЖЕН СЕКРЕТНЫЙ СУНДУК!** 📦\n\nКто первый нажмет на кнопку — заберет награду!",
                        reply_markup=chest_kb, parse_mode="Markdown"
                    )
                    # Фиксируем заброс в логе активности
                    log = ActivityLog(user_id=0, chat_id=chat.id, platform="tg", earned_rating=0)
                    session.add(log)
                except Exception as e:
                    logger.error(f"Ошибка заброса сундука в TG чат {chat.id}: {e}")
            elif chat.platform == "discord":
                # КРОСС-ШЛЮЗ ДЛЯ ДИСКОРДА: Сюда встанет вызов API дискорд-клиента
                pass
                
        await session.commit()


async def finalize_active_giveaways(bot: Bot):
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()
        
        # --- ФАЗА 1: ЧИСТАЯ ПУБЛИКАЦИЯ АНОНСОВ ---
        # Ищем новые розыгрыши, время анонса которых подошло
        announce_q = select(Giveaway).where(
            and_(Giveaway.announce_at <= now, Giveaway.status == "created")
        )
        gas_to_announce = (await session.execute(announce_q)).scalars().all()
        
        chats_q = select(ChatConfig).where(
            and_(ChatConfig.is_active == True, ChatConfig.platform == "tg")
        )
        active_tg_chats = (await session.execute(chats_q)).scalars().all()
        
        for ga in gas_to_announce:
            # 🛡️ ПРЕДОХРАНИТЕЛЬ: Очищаем типы от возможных сырых списков сплита
            r_type = str(ga.reward_type).replace("[", "").replace("]", "").replace("'", "").split(",")[-1].strip()
            c_type = str(ga.condition_type).replace("[", "").replace("]", "").replace("'", "").split(",")[-1].strip()
            
            # Корректно определяем приз на основе чистого текстового маркера
            if "rating" in r_type or r_type == "rating":
                prize = f"💰 {ga.reward_value} {settings.CURRENCY_NAME}"
            else:
                prize = f"🛍️ Мерч: '{ga.reward_value}'"
                
            # Корректно определяем No-Code допуск по билетам или титулам
            if "ticket" in c_type or c_type == "ticket":
                ticket_item = await session.get(ShopItem, int(ga.condition_value))
                t_lbl = ticket_item.name if ticket_item else f"Билет #{ga.condition_value}"
                cond_text = f"🎟️ **Участие ПЛАТНОЕ:** требуется купить билет **'{t_lbl}'** на Витрине!"
                
                # При платном билете сквозной титул берем из min_title_id
                t_info = settings.parsed_titles.get(int(ga.min_title_id))
                t_name = t_info.name if t_info else "Новичок"
            else:
                ticket_item = None
                t_info = settings.parsed_titles.get(int(ga.min_title_id))
                t_name = t_info.name if t_info else "Новичок"
                cond_text = f"💬 **Участие СВОБОДНОЕ:** просто общайтесь в чатах проекта!"
                
            for chat in active_tg_chats:
                try:
                    await bot.send_message(
                        chat_id=chat.id,
                        text=f"🎉 **СТАРТУЕТ НОВЫЙ РОЗЫГРЫШ!** 🎉\n\n"
                             f"🎁 **Приз:** {prize}\n"
                             f"🎖️ **Минимальный ранг:** не ниже *'{t_name}'*\n"
                             f"{cond_text}\n\n"
                             f"⏳ **Финал лотереи (UTC):** {ga.finalize_at.strftime('%d.%m %H:%M')}\n"
                             f"💬 Планировщик автоматически выберет победителей среди подходящих участников!",
                        parse_mode="Markdown"
                    )
                except Exception: pass
                
            ga.status = "active"
            
        await session.commit()

        finalize_q = select(Giveaway).where(
            and_(Giveaway.finalize_at <= now, Giveaway.status == "active")
        )
        gas_to_finalize = (await session.execute(finalize_q)).scalars().all()
        
        for ga in gas_to_finalize:
            unique_uids = []
            
            # Чистим строку условия от списков
            c_type = str(ga.condition_type).replace("[", "").replace("]", "").replace("'", "").split(",")[-1].strip()
            r_type = str(ga.reward_type).replace("[", "").replace("]", "").replace("'", "").split(",")[-1].strip()
            
            # Вектор А: Лотерея по билетам из Магазина
            if "ticket" in c_type or c_type == "ticket":
                ticket_id = int(ga.condition_value)
                units_q = select(StockUnit.owner_id).where(
                    and_(
                        StockUnit.item_id == ticket_id,
                        StockUnit.status == "sold",
                        StockUnit.owner_id > 0
                    )
                )
                raw_buyers = (await session.execute(units_q)).scalars().all()
                unique_uids = list(set(raw_buyers))
            # Вектор Б: Лотерея свободная по логам активности чата
            else:
                logs_q = select(ActivityLog.user_id).where(
                    and_(
                        ActivityLog.created_at >= ga.announce_at,
                        ActivityLog.created_at <= now,
                        ActivityLog.user_id > 0
                    )
                )
                raw_chatters = (await session.execute(logs_q)).scalars().all()
                unique_uids = list(set(raw_chatters))
                
            if not unique_uids:
                ga.status = "finished"
                await session.commit()
                continue
                
            # СКВОЗНОЙ ЦЕНЗ ПО ТИТУЛАМ ОПЫТА ДЛЯ ОБОИХ ВЕКТОРОВ
            eligible_users = []
            req_title_id = int(ga.min_title_id)
            
            for uid in unique_uids:
                u = await session.get(User, uid)
                if not u or u.is_banned: continue
                
                u_title_id = 1
                for t in sorted(settings.parsed_titles.values(), key=lambda x: x.min_rating, reverse=True):
                    if u.lifetime_rating >= t.min_rating:
                        u_title_id = t.id
                        break
                if u_title_id >= req_title_id:
                    eligible_users.append(u)
                    
            if not eligible_users:
                ga.status = "finished"
                await session.commit()
                continue
                
            actual_winners_count = min(len(eligible_users), ga.winners_count)
            winners = random.sample(eligible_users, k=actual_winners_count)
            
            # Начисление заслуженных призов
            for winner in winners:
                if "rating" in r_type or r_type == "rating":
                    amount = int(ga.reward_value)
                    winner.current_rating += amount
                    winner.lifetime_rating += amount
                    try:
                        await bot.send_message(
                            chat_id=winner.tg_id,
                            text=f"🎉 **Вы выиграли в лотерее Оверлорда!**\n"
                                 f"Награда: +{amount} {settings.CURRENCY_NAME} зачислена."
                        )
                    except Exception: pass
                else:
                    item_q = select(ShopItem).where(
                        and_(ShopItem.name == ga.reward_value, ShopItem.is_deleted == False)
                    ).limit(1)
                    shop_item = (await session.execute(item_q)).scalar_one_or_none()
                    
                    unit = None
                    if shop_item:
                        unit_q = select(StockUnit).where(
                            and_(StockUnit.item_id == shop_item.id, StockUnit.status == "stock")
                        ).limit(1)
                        unit = (await session.execute(unit_q)).scalar_one_or_none()
                        
                    if unit and shop_item:
                        unit.status = "won"
                        unit.owner_id = winner.tg_id
                        unit.purchase_source = "giveaway"
                        unit.serial_or_promo = "[НЕ ОФОРМЛЕНО]"
                        try:
                            await bot.send_message(
                                chat_id=winner.tg_id,
                                text=f"🎉 **Вы выиграли приз: {shop_item.name}!**\n"
                                     f"Зайдите в '🎒 Мой Инвентарь' для оформления доставки.",
                                parse_mode="Markdown"
                            )
                        except Exception: pass
                    else:
                        fallback_coins = 150
                        winner.current_rating += fallback_coins
                        winner.lifetime_rating += fallback_coins
                        try:
                            await bot.send_message(
                                chat_id=winner.tg_id,
                                text=f"🎁 На складе не оказалось мерча '{ga.reward_value}'. "
                                     f"Вам начислена компенсация: +{fallback_coins} поинтов!",
                                parse_mode="Markdown"
                            )
                        except Exception: pass

            # АТОМАРНОЕ АННУЛИРОВАНИЕ БИЛЕТОВ
            if "ticket" in c_type or c_type == "ticket":
                burn_stmt = update(StockUnit).where(
                    and_(StockUnit.item_id == int(ga.condition_value), StockUnit.status == "sold")
                ).values(status="spent", serial_or_promo=f"[ИСПОЛЬЗОВАН В ЛОТЕРЕЕ #{ga.id}]")
                await session.execute(burn_stmt)

            ga.status = "finished"
            winners_mentions = ", ".join([f"ID: {w.tg_id}" for w in winners])
            for chat in active_tg_chats:
                try:
                    await bot.send_message(
                        chat_id=chat.id,
                        text=f"🏁 **Лотерея #{ga.id} официально завершена!**\n\n"
                             f"🎁 Разыгрывался приз: *{ga.reward_value}*\n"
                             f"🏆 Победители: {winners_mentions}\n\n"
                             f"Награды выданы, использованные билеты аннулированы!",
                        parse_mode="Markdown"
                    )
                except Exception: pass
                
        await session.commit()


def start_scheduler(bot: Bot):
    """Регистрирует минутные задачи интервального сканирования Беты."""
    if not scheduler.running:
        scheduler.add_job(
            check_and_send_random_chests,
            "interval",
            minutes=1,
            args=[bot],
            id="check_and_send_random_chests",
            replace_existing=True
        )
        scheduler.add_job(
            finalize_active_giveaways,
            "interval",
            minutes=1,
            args=[bot],
            id="finalize_active_giveaways",
            replace_existing=True
        )
        scheduler.start()
        logger.info("⏰ Кроссплатформенный планировщик APScheduler успешно запущен.")


