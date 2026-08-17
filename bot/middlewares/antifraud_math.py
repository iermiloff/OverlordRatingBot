import time
import logging
import numpy as np
from aiogram import BaseMiddleware
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import User, ActivityLog

logger = logging.getLogger(__name__)

# Критический порог стандартного отклонения в секундах. 
# Если разброс интервалов между сообщениями меньше 3.5 секунд — это гарантированный кликер/скрипт.
AF_THRESHOLD_SIGMA = 3.5 
MIN_MESSAGES_TO_ANALYZE = 8

class AntiFraudMathMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        # Проверяем только текстовые сообщения внутри активных групповых чатов
        if not isinstance(event, Message) or not event.chat.type.in_(["group", "supergroup"]) or not event.text:
            return await handler(event, data)

        user_id = event.from_user.id
        
        # Исключение: Менеджеры системы никогда не проверяются антифродом
        if user_id in settings.managers_list:
            return await handler(event, data)

        db_session: AsyncSession = data.get("db_session")
        db_user: User = data.get("db_user")

        if not db_session or not db_user:
            return await handler(event, data)

        # Вытаскиваем временные метки последних сообщений пользователя из логов активности
        logs_q = (
            select(ActivityLog.created_at)
            .where(and_(ActivityLog.user_id == user_id, ActivityLog.message_length > 0))
            .order_by(ActivityLog.created_at.desc())
            .limit(15)
        )
        logs_res = await db_session.execute(logs_q)
        timestamps = logs_res.scalars().all()

        # Если истории сообщений еще мало, пропускаем математический анализ
        if len(timestamps) < MIN_MESSAGES_TO_ANALYZE:
            return await handler(event, data)

        # Переводим объекты datetime в Unix-timestamp (секунды) и считаем интервалы
        unix_times = [t.timestamp() for t in timestamps]
        
        # Считаем разницу между соседними сообщениями (интервалы отправки)
        intervals = []
        for i in range(len(unix_times) - 1):
            intervals.append(abs(unix_times[i] - unix_times[i+1]))

        # Вычисляем стандартное отклонение (Standard Deviation) числового массива интервалов
        sigma = float(np.std(intervals))
        mean_interval = float(np.mean(intervals))

        # АНАЛИЗ НА КЛИКЕР-БОТА
        if sigma < AF_THRESHOLD_SIGMA and mean_interval < 45.0:
            # Юзер отправляет сообщения с одинаковыми интервалами! Защита срабатывает.
            if not db_user.is_suspicious:
                db_user.is_suspicious = True
                reason = f"🤖 Кликер-бот / Макрос (σ={round(sigma, 2)}с, средний интервал={round(mean_interval, 1)}с)"
                db_user.antifraud_reason = reason
                await db_session.commit()

                # Формируем CRM-карточку экстренного алерта для менеджеров
                alert_text = (
                    f"🚨 **КРИТИЧЕСКИЙ СИГНАЛ АНТИФРОД-СИСТЕМЫ** 🚨\n\n"
                    f"⚠️ Выявлен автоматический спам-скрипт / кликер опыта!\n\n"
                    f"👤 **Нарушитель:** {event.from_user.mention_html()}\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"📊 **Математические метрики фрода:**\n"
                    f"▪️ Стандартное отклонение интервалов (σ): ` {round(sigma, 3)} ` сек.\n"
                    f"▪️ Среднее время между сообщениями: ` {round(mean_interval, 1)} ` сек.\n"
                    f"▪️ Проанализировано базы: `{len(timestamps)}` сообщений\n\n"
                    f"🛑 Робот зафиксировал идеальный тайминг отправки фраз. Профиль заблокирован до решения оверлордов."
                )

                # Кнопка мгновенной блокировки из ЛС админа
                af_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🔨 Подтвердить Бан и Анулировать", callback_data=f"af_confirm_ban:{user_id}"),
                        InlineKeyboardButton(text="✅ Ложная тревога / Помиловать", callback_data=f"af_pardon:{user_id}")
                    ]
                ])

                # Рассылаем экстренные карточки абузера всем менеджерам в личку
                for manager_id in settings.managers_list:
                    try:
                        await event.bot.send_message(
                            chat_id=manager_id, 
                            text=alert_text, 
                            reply_markup=af_kb, 
                            parse_mode="HTML"
                        )
                    except Exception: pass

            # Блокируем начисление рейтинга за это сообщение абузера ( handler НЕ вызывается!)
            return

        # Если всё в порядке — передаем управление дальше по цепочке
        return await handler(event, data)
