import enum
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class OrderStatus(enum.Enum):
    CREATED = "created"       # Покупка/выигрыш только что созданы
    PROCESSED = "processed"   # В обработке у менеджера
    COMPLETED = "completed"   # Успешно выдано/отправлено
    REJECTED = "rejected"     # Отменено менеджером (например, фрод)

class User(Base):
    __tablename__ = "users"
    
    tg_id = Column(BigInteger, primary_key=True)
    username = Column(String(32), nullable=True)
    full_name = Column(String(128), nullable=False)
    
    # Раздельная система рейтинга
    current_rating = Column(Integer, default=0)   # Баланс для трат в магазине
    lifetime_rating = Column(Integer, default=0)  # Несгораемый опыт для титулов
    
    # Реферальная система
    referrer_id = Column(BigInteger, ForeignKey("users.tg_id"), nullable=True)
    is_ref_reward_paid = Column(Boolean, default=False) # Выплачен ли бонус пригласившему
    
    # Статусы анти-фрода и баны
    is_banned = Column(Boolean, default=False)
    ban_until = Column(DateTime, nullable=True)
    is_suspicious = Column(Boolean, default=False)       # Подсветка в админке
    antifraud_reason = Column(Text, nullable=True)       # Обоснование для менеджера
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
class ChatConfig(Base):
    __tablename__ = "chats_config"
    id = Column(BigInteger, primary_key=True)  # Telegram Chat ID группы
    title = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)  # Считаем ли тут активность
    invite_link = Column(String(256), nullable=True)  # Сюда бот сохранит ссылку


class ShopItem(Base):
    __tablename__ = "shop_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Integer, nullable=False)
    is_deleted = Column(Boolean, default=False) # Мягкое удаление (защита истории заказов)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.tg_id"))
    source = Column(String(32), nullable=False)   # "shop", "chest" или "giveaway"
    item_name = Column(String(128), nullable=False) # Какое имя товара было на момент заказа
    status = Column(Enum(OrderStatus), default=OrderStatus.CREATED)
    delivery_data = Column(Text, nullable=True)   # Контакты и адрес доставки
    created_at = Column(DateTime, default=datetime.utcnow)

class ChestReward(Base):
    __tablename__ = "chest_rewards"
    id = Column(Integer, primary_key=True, autoincrement=True)
    reward_type = Column(String(32), nullable=False)  # "rating" или "physical"
    value = Column(String(128), nullable=False)       # Кол-во рейтинга или название мерча
    weight = Column(Float, default=1.0)               # Вес (шанс выпадения)

class PromoChannel(Base):
    __tablename__ = "promo_channels"
    id = Column(BigInteger, primary_key=True)         # ID телеграм-канала
    invite_link = Column(String(256), nullable=False)
    reward = Column(Integer, default=0)               # Цена подписки в рейтинге

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.tg_id"))
    chat_id = Column(BigInteger, nullable=False)
    message_length = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow) # Каждое сообщение пишется сюда
    
class SystemSettings(Base):
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, default=1)
    chest_open_price = Column(Integer, default=0)       # Цена открытия
    chest_min_title_id = Column(Integer, default=1)     # Минимальный титул
    chest_quiet_hours = Column(Integer, default=12)     # Слой тишины (сон в часах)
    chest_random_hours = Column(Integer, default=12)    # Диапазон рандома (в часах)
