import logging
import random
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_

from config import settings
from database.connection import AsyncSessionLocal
from database.models import Giveaway, User, ChatConfig, ShopItem, Inventory

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def check_and_process_giveaways(bot):
    """Каждоминутный фоновый воркер для проверки и автоматического проведения лотерей."""
    now = datetime.utcnow()
    
    async with AsyncSessionLocal() as session:
        # 1. СЕКЦИЯ АВТО-АНОНСОВ
        announce_q = select(Giveaway).where(and_(Giveaway.status == "created", Giveaway.announce_at <= now))
        to_announce = (await session.execute(announce_q)).scalars().all()
        
        for ga in to_announce:
            parts = str(ga.condition_value).split(":")
            title_id = int(parts[0])  # ИСПРАВЛЕНО: Добавлен точный индекс 0
            ticket_id = int(parts[1]) # ИСПРАВЛЕНО: Добавлен точный индекс 1
            
            t_name = settings.parsed_titles.get(title_id).name
            
            # Динамически форматируем призовой баланс с валютой и эмодзи из настроек .env
            prize_currency = f"{settings.CURRENCY_EMOJI} {ga.reward_value} {settings.CURRENCY_NAME}" if ga.reward_type == "rating" else f"🎒 {ga.reward_value}"

            # Адаптивно перестраиваем текст требований под выбранный админом режим (combo или открытый)
            if ticket_id == 0:
                cond_text = f"1. 🎖️ Наличие титула от **'{t_name}'** и выше.\n" \
                            f"2. 🔓 Участие **БЕСПЛАТНОЕ**, лотерейные билеты не требуются!"
                footer_text = "ℹ️ _Вам не нужно никуда нажимать! Бот автоматически просканирует чат и выберет победителей среди тех, кто подходит по критериям!_"
            else:
                ticket_item = await session.get(ShopItem, ticket_id)
                ticket_name = ticket_item.name if ticket_item else "Удаленный билет"
                cond_text = f"1. 🎖️ Наличие титула от **'{t_name}'** и выше.\n" \
                            f"2. 🎟️ Наличие билета **'{ticket_name}'** в вашем инвентаре."
                footer_text = f"📈 _Покупайте билеты в '🛍️ Магазин товаров'! Каждый билет пропорционально умножает ваши шансы в лотерейном барабане бота!_"

            chats = (await session.execute(select(ChatConfig).where(ChatConfig.is_active == True))).scalars().all()
            
            text_announce = (
                "🎉 **ВНИМАНИЕ! ЗАПЛАНИРОВАН АВТОМАТИЧЕСКИЙ РОЗЫГРЫШ!** 🎉\n\n"
                f"🎁 **Приз лотереи:** {prize_currency}\n"
                f"🏆 **Призовых мест:** {ga.winners_count}\n"
                f"⏳ **Авто-финал состоится:** `{ga.finalize_at.strftime('%d.%m.%Y %H:%M')}` (UTC сервера)\n\n"
                f"🔒 **КРИТЕРИИ АВТО-ОТБОРА УЧАСТНИКОВ:**\n{cond_text}\n\n"
                f"{footer_text}"
            )
            
            for chat in chats:
                try: await bot.send_message(chat_id=chat.id, text=text_announce, parse_mode="Markdown")
                except Exception: pass
                
            ga.status = "announced"
        
        # 2. СЕКЦИЯ АВТО-ФИНАЛОВ
        finalize_q = select(Giveaway).where(and_(Giveaway.status == "announced", Giveaway.finalize_at <= now))
        to_finalize = (await session.execute(finalize_q)).scalars().all()
        
        for ga in to_finalize:
            parts = str(ga.condition_value).split(":")
            title_id = int(parts[0])  # ИСПРАВЛЕНО: Добавлен точный индекс 0
            ticket_id = int(parts[1]) # ИСПРАВЛЕНО: Добавлен точный индекс 1
            
            min_rating = settings.parsed_titles.get(title_id).min_rating
            prize_currency = f"{settings.CURRENCY_EMOJI} {ga.reward_value} {settings.CURRENCY_NAME}" if ga.reward_type == "rating" else f"*{ga.reward_value}*"

            # Адаптивная выборка участников из базы данных
            if ticket_id == 0:
                users_q = select(User).where(and_(User.lifetime_rating >= min_rating, User.is_banned == False))
                query_res = await session.execute(users_q)
                eligible_records = [(u, 1) for u in query_res.scalars().all()] # У всех по 1 равному шансу
            else:
                users_q = select(User, Inventory.quantity).join(Inventory, Inventory.user_id == User.tg_id).where(and_(
                    User.lifetime_rating >= min_rating, Inventory.item_id == ticket_id, Inventory.quantity >= 1, User.is_banned == False
                ))
                eligible_records = (await session.execute(users_q)).all()

            if not eligible_records:
                ga.status = "finished"
                continue

            # Построение лотерейного барабана весов
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

            # Проведение начислений и утилизация купонов
            mentions = []
            for w in winners:
                if ticket_id > 0:
                    inv_q = select(Inventory).where(and_(Inventory.user_id == w.tg_id, Inventory.item_id == ticket_id))
                    ticket = (await session.execute(inv_q)).scalar_one_or_none()
                    if ticket: 
                        ticket.quantity -= 1

                if ga.reward_type == "rating":
                    w.current_rating += int(ga.reward_value)
                    w.lifetime_rating += int(ga.reward_value)
                
                qty_label = f" _(купон из {user_ticket_map[w.tg_id]} билетов)_" if ticket_id > 0 else ""
                mentions.append(f"👑 @{w.username or w.full_name}{qty_label}")

            # Публикация итогов лотереи по чатам
            chats = (await session.execute(select(ChatConfig).where(ChatConfig.is_active == True))).scalars().all()
            winners_str = "\n".join(mentions)
            text_results = (
                "🎉 **АВТОМАТИЧЕСКИЙ РОЗЫГРЫШ ЗАВЕРШЕН!** 🎉\n\n"
                f"🎁 **Разыгранный приз:** {prize_currency}\n"
                f"🏆 **Список наших счастливых победителей:**\n{winners_str}\n\n"
                "Поздравляем счастливчиков! Счастливые билеты списаны, а награды уже зачислены на ваши балансы! 👏👏"
            )
            for chat in chats:
                try: await bot.send_message(chat_id=chat.id, text=text_results, parse_mode="Markdown")
                except Exception: pass
                
            ga.status = "finished"
            
        await session.commit()

def start_scheduler(bot):
    """Запуск фонового планировщика внутри главного процесса asyncio."""
    scheduler.add_job(check_and_process_giveaways, 'interval', minutes=1, args=[bot])
    scheduler.start()
    logger.info("⏰ Фоновый планировщик APScheduler успешно запущен!")
