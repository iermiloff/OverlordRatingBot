from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database.models import User, Inventory, ShopItem
from bot.keyboards.menu_kb import get_back_to_menu_keyboard

router = Router(name="user_inventory_router")

@router.callback_query(F.data == "user_inventory")
async def show_user_inventory_inline(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    """Отображает список всех предметов и билетов в инвентаре пользователя."""
    # Извлекаем все предметы пользователя, у которых количество больше 0
    query = (
        select(Inventory, ShopItem)
        .join(ShopItem, Inventory.item_id == ShopItem.id)
        .where(Inventory.user_id == db_user.tg_id, Inventory.quantity > 0)
        .order_by(ShopItem.name)
    )
    result = await db_session.execute(query)
    items_data = result.all()

    if not items_data:
        text = (
            "🎒 **Мой Инвентарь**\n\n"
            "Ваш рюкзак пока пуст! 📁\n"
            "Здесь будут отображаться ваши игровые предметы и лотерейные билеты.\n\n"
            f"🛒 Вы можете приобрести билеты для розыгрышей в разделе **Магазин товаров**."
        )
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
        await callback.answer()
        return

    lines = [
        "🎒 **Твой личный инвентарь предметов:**\n",
        "Эти предметы находятся у тебя в рюкзаке и могут использоваться для участия в розыгрышах или интерактивах:\n"
    ]

    for idx, (inv, item) in enumerate(items_data, start=1):
        item_type = "🎟️ Билет" if item.is_ticket else "📦 Предмет"
        lines.append(f"{idx}. {item_type} **\"{item.name}\"** — {inv.quantity} шт.")

    text = "\n".join(lines)
    
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(to_manager=False), parse_mode="Markdown")
    await callback.answer()
