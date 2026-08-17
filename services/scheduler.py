import logging
import random
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_, delete, func

from config import settings
from database.connection import AsyncSessionLocal
from database.models import Giveaway, User, ChatConfig, ShopItem, Inventory, Order, OrderStatus, ActivityLog

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def send_daily_top_10(bot):
    """Ежедневный воркер: собирает топ-10 активистов за последние 24 часа и шлет в чаты."""
    now = datetime.utcnow()
    one_day_ago = now - timedelta(days=1)
    
    async with AsyncSessionLocal() as session:
        # Группируем логи активности за сутки, считаем сообщения живых пользователей
        top_query = (
            select(User, func.count(ActivityLog.id).label("msg_count"))
            .join(ActivityLog, ActivityLog.user_id == User.tg_id)
            .where(and_(
                ActivityLog.created_at >= one_day_ago,
                ActivityLog.message_length > 0,
                User.is_banned == False,
                User.tg_id.not_in(settings.managers_list) # Исключаем админов из топа
            ))
            .group_by(User.tg_id)
            .order_by(func.count(ActivityLog.id).desc())
            .limit(10)
        )
        
        res = await session.execute(top_query)
        records = res.all()
        
        if not records:
            logger.info("📢 Ежедневный топ-10 пуст (нет активности за 24 часа). Рассылка отменена.")
            return

        lines = [
            "🏆 **ЕЖЕДНЕВНАЯ ДОСКА ПОЧЕТА ЧАТА | ТОП-10 АКТИВИСТОВ** 🏆\n",
            "Поздравляем наших самых разговорчивых участников за последние 24 часа! Ваши награды и ранги растут с каждым словом:\n"
        ]
        
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for idx, (user_obj, msg_count) in enumerate(records):
            medal = medals[idx] if idx < len(medals) else "👤"
            username_label = f"@{user_obj.username}" if user_obj.username else user_obj.full_name
            lines.append(f"{medal} {username_label} — **{msg_count}** сообщений")
            
        lines.append(f"\n💬 Общайтесь активнее, зарабатывайте {settings.CURRENCY_NAME} и забирайте призы в магазине! Новая доска почета — завтра в это же время! 🚀")
        text_top = "\n".join(lines)
        
        # Публикуем доску почета во все привязанные группы
        chats = (await session.execute(select(ChatConfig).where(ChatConfig.is_active == True))).scalars().all()
        for chat in chats:
            try: await bot.send_message(chat_id=chat.id, text=text_top, parse_mode="Markdown")
            except Exception: pass
            
        logger.info("🏆 Ежедневная доска почета топ-10 успешно разослана по чатам!")

async def check_and_process_giveaways(bot):
    """Каждоминутный фоновый воркер для проверки и автоматического проведения лотерей."""
    now = datetime.utcnow()
    
    async with AsyncSessionLocal() as session:
        # 1. СЕКЦИЯ АВТО-АНОНСОВ
        announce_q = select(Giveaway).where(and_(Giveaway.status == "created", Giveaway.announce_at <= now))
        to_announce = (await session.execute(announce_q)).scalars().all()
        
        for ga in to_announce:
            parts = str(ga.condition_value).split(":")
            title_id = int(parts[0])
            ticket_id = int(parts[1])
            
            t_name = settings.parsed_titles.get(title_id).name
            
            # Умное распознавание типа приза (если только цифры — это валюта рейтинга)
            is_rating_prize = ga.reward_type == "rating" or str(ga.reward_value).strip().isdigit()
            if is_rating_prize:
                prize_currency = f"{settings.CURRENCY_EMOJI} {ga.reward_value} {settings.CURRENCY_NAME}"
            else:
                prize_currency = f"🎒 {ga.reward_value}"

            # Адаптивно перестраиваем текст требований под выбранный админом режим
            if ticket_id == 0:
                cond_text = f"1. 🎖️ Наличие титула от **'{t_name}'** и выше.\n" \
                            f"2. 🔓 Участие **БЕСПЛАТНОЕ**, лотерейные билеты не требуются!"
                footer_text = "ℹ️ _Вам не нужно никуда нажимать! Бот автоматически просканирует чат и выберет победителей среди тех, кто подходит по критериям!_"
            else:
                ticket_item = await session.get(ShopItem, ticket_id)
                ticket_name = ticket_item.name if ticket_item else "Удаленный билет"
                cond_text = f"1. 🎖️ Наличие титула от **'{t_name}'** и выше.\n" \
                            f"2. 🎟️ Наличие билета **'{ticket_name}'** в вашем инвентаре."
                footer_text = f"📈 _Покупайте билеты в '🛍️ Магазин товаров'! Каждый билет пропорционально умножает ваши шансы в лотерейном барабане бота!_\n\n" \
                              f"⚠️ **ВНИМАНИЕ:** В случае победы у счастливчика **сгорают ВСЕ билеты данного типа**, обнуляя его шансы для следующего раунда! У проигравших билеты сохраняются! 🎇"

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
            title_id = int(parts[0])
            ticket_id = int(parts[1])
            
            min_rating = settings.parsed_titles.get(title_id).min_rating
            
            is_rating_prize = ga.reward_type == "rating" or str(ga.reward_value).strip().isdigit()
            if is_rating_prize:
                prize_currency = f"{settings.CURRENCY_EMOJI} {ga.reward_value} {settings.CURRENCY_NAME}"
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
                users_q = select(User, Inventory.quantity).join(Inventory, Inventory.user_id == User.tg_id).where(and_(
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
                        delivery_data="Выиграно в автоматическом розыгрыше чата. Предоставьте данные менеджеру."
                    )
                    session.add(new_order)
                    
                    for manager_id in settings.managers_list:
                        try:
                            await bot.send_message(
                                chat_id=manager_id,
                                text=f"🎁 **Розыгрыш в чате завершен! Мерч ждет отправки!**\n\n"
                                     f"👤 Победитель: @{w.username or w.tg_id}\n"
                                     f"🎒 Награда: *{ga.reward_value}*\n"
                                     f"Заявка автоматически добавлена в раздел '📥 Заявки/Заказы'.",
                                parse_mode="Markdown"
                            )
                        except Exception: pass
                
                qty_label = f" _(заявил {user_ticket_map[w.tg_id]} шт. билетов)_" if ticket_id > 0 else ""
                mentions.append(f"👑 @{w.username or w.full_name}{qty_label}")

            if ticket_id > 0 and winner_ids:
                burn_query = delete(Inventory).where(and_(
                    Inventory.item_id == ticket_id,
                    Inventory.user_id.in_(winner_ids)
                ))
                await session.execute(burn_query)
                footer_status_text = "Победители полностью обнулили свои билеты! У остальных участников купоны сохранены для следующих лотерей! 🔥"
            else:
                footer_status_text = "Награды уже успешно зачислены в ваши личные кабинеты! 👏"

            chats = (await session.execute(select(ChatConfig).where(ChatConfig.is_active == True))).scalars().all()
            winners_str = "\n".join(mentions)
            text_results = (
                "🎉 **АВТОМАТИЧЕСКИЙ РОЗЫГРЫШ ЗАВЕРШЕН!** 🎉\n\n"
                f"🎁 **Разыгранный приз:** {prize_currency}\n"
                f"🏆 **Список наших счастливых победителей:**\n{winners_str}\n\n"
                f"Поздравляем счастливчиков! {footer_status_text}"
            )
            for chat in chats:
                try: await bot.send_message(chat_id=chat.id, text=text_results, parse_mode="Markdown")
                except Exception: pass
                
            ga.status = "finished"
            
        await session.commit()

def start_scheduler(bot):
    """Запуск фонового планировщика внутри главного процесса asyncio."""
    # 1. Каждоминутный воркер проверки сетки розыгрышей (анонсы и финалы)
    scheduler.add_job(check_and_process_giveaways, 'interval', minutes=1, args=[bot])
    
    # 2. Ежедневный воркер публикации доски почета Топ-10 активистов (раз в 24 часа)
    scheduler.add_job(send_daily_top_10, 'interval', hours=24, args=[bot])
    
    scheduler.start()
    logger.info("⏰ Фоновый планировщик APScheduler (Розыгрыши + Топ-10 за 24ч) успешно запущен!")
