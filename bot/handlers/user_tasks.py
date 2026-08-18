import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database.models import User, PromoChannel, ActivityLog, StockUnit, ShopItem

router = Router(name="user_tasks_router")
logger = logging.getLogger(__name__)

# --- 📋 ВЫВОД СПИСКА ДОСТУПНЫХ ЗАДАНИЙ ---

@router.message(F.text == "🎯 Квесты / Задания Оверлорда")
@router.callback_query(F.data == "user_tasks_main")
async def cmd_user_tasks_main(message_or_query, db_session: AsyncSession, db_user: User):
    """Отображение текущих квестов с проверкой по новой ERP таблице StockUnit."""
    is_callback = isinstance(message_or_query, CallbackQuery)
    
    # Квест 1: Проверка подписки на обязательный канал
    promo_q = select(PromoChannel).where(PromoChannel.is_required == True).limit(1)
    promo = (await db_session.execute(promo_q)).scalar_one_or_none()
    
    # Квест 2: Проверка факта покупки мерча в магазине через StockUnit со статусом 'sold'
    items_bought_q = select(StockUnit).where(
        and_(StockUnit.owner_id == db_user.tg_id, StockUnit.status == "sold")
    ).limit(1)
    has_bought_merch = (await db_session.execute(items_bought_q)).scalar_one_or_none()
    
    txt_q1 = "✅ Выполнено! (+50 поинтов)" if db_user.lifetime_rating >= 50 else "⏳ Не выполнено (Подпишитесь на канал)"
    txt_q2 = "✅ Выполнено! (+100 поинтов)" if has_bought_merch else "⏳ Не выполнено (Купите любой товар на Витрине)"
    
    text = (
        "🎯 **Интерактивные Задания и Квесты Оверлорда**\n\n"
        "Выполняйте задания, чтобы прокачать свой ранг и заработать монеты:\n\n"
        f"1. 📢 **Первый шаг к лояльности**\n"
        f"▪️ Критерий: Подписка на промо-канал.\n"
        f"▪️ Статус: `{txt_q1}`\n\n"
        f"2. 🎒 **Покровитель Склада**\n"
        f"▪️ Критерий: Приобрести любую вещь на Витрине магазина.\n"
        f"▪️ Статус: `{txt_q2}`\n\n"
        "👇 Используйте кнопки ниже для верификации:"
    )
    
    buttons = []
    if promo:
        buttons.append([InlineKeyboardButton(text="📢 Перейти к каналу", url=promo.invite_link or "https://t.me")])
        
    buttons.append([InlineKeyboardButton(text="🔄 Проверить выполнение квестов", callback_data="user_tasks_check")])
    buttons.append([InlineKeyboardButton(text="↩️ В главное меню ЛК", callback_data="user_lk_main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if is_callback:
        try: await message_or_query.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception: pass
    else:
        await message_or_query.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- 🔄 ВЕРИФИКАЦИЯ ВЫПОЛНЕНИЯ КВЕСТОВ ---

@router.callback_query(F.data == "user_tasks_check")
async def process_user_tasks_verification(
    callback: CallbackQuery, db_session: AsyncSession, db_user: User
):
    """Проверка выполнения квестов по актуальным поштучным данным ERP."""
    # 1. Сканируем наличие купленных единиц на имя пользователя
    units_q = select(StockUnit).where(
        and_(StockUnit.owner_id == db_user.tg_id, StockUnit.status == "sold")
    ).limit(1)
    has_bought_merch = (await db_session.execute(units_q)).scalar_one_or_none()
    
    # 2. Логика начисления наград за прохождение (пример триггеров опыта)
    rewards_awarded = 0
    msg_alert = ""
    
    if has_bought_merch and db_user.lifetime_rating < 100:
        # Условный триггер: если это первая покупка, поощряем баланс
        bonus = 100
        db_user.current_rating += bonus
        db_user.lifetime_rating += bonus
        rewards_awarded += bonus
        msg_alert += f"🎒 Квест 'Покровитель Склада' выполнен! +{bonus} поинтов!\n"
        
    if rewards_awarded > 0:
        await db_session.commit()
        await callback.answer(f"🎉 Успех!\n{msg_alert}", show_alert=True)
    else:
        await callback.answer(
            "⏳ Новых выполненных условий не найдено. "
            "Продолжайте проявлять активность в чатах!", 
            show_alert=True
        )
        
    # Обновляем интерфейс заданий
    await cmd_user_tasks_main(
        message_or_query=callback, 
        db_session=db_session, 
        db_user=db_user
    )

