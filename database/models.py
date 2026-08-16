from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, ForeignKey, Float
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import enum

Base = declarative_base()

class OrderStatus(str, enum.Enum):
    """Глобальное перечисление статусов обработки заказов и наград."""
    CREATED = "created"      # Создан / ожидает менеджера
    PROCESSED = "processed"  # Менеджер взял в работу
    COMPLETED = "completed"  # Выдан / отправлен клиенту
    REJECTED = "rejected"    # Отклонен менеджером

class User(Base):
    __tablename__ = "users"
    
    tg_id = Column(BigInteger, primary_key=True)
    username = Column(String(32), nullable=True)
    full_name = Column(String(128), nullable=False)
    current_rating = Column(Integer, default=0)
    lifetime_rating = Column(Integer, default=0)
    referrer_id = Column(BigInteger, nullable=True)
    is_banned = Column(Boolean, default=False)
    ban_until = Column(DateTime, nullable=True)
    is_suspicious = Column(Boolean, default=False)
    antifraud_reason = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Реляционные связи
    inventory = relationship("Inventory", back_populates="user", cascade="all, delete-orphan")

class ShopItem(Base):
    __tablename__ = "shop_items"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(String(512), nullable=True)
    price = Column(Integer, nullable=False)
    image_url = Column(String(256), nullable=True) # Ссылка на фото или GIF в Telegram
    is_ticket = Column(Boolean, default=False)     # Флаг лотерейного билета
    is_deleted = Column(Boolean, default=False)

class Inventory(Base):
    __tablename__ = "user_inventories"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"))
    item_id = Column(Integer, ForeignKey("shop_items.id", ondelete="CASCADE"))
    quantity = Column(Integer, default=1)
    
    user = relationship("User", back_populates="inventory")
    item = relationship("ShopItem")

class ChestReward(Base):
    __tablename__ = "chest_rewards"
    id = Column(Integer, primary_key=True, autoincrement=True)
    reward_type = Column(String(32), nullable=False) # "rating" или "physical"
    value = Column(String(128), nullable=False)
    weight = Column(Float, default=1.0)

class Giveaway(Base):
    __tablename__ = "giveaways"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reward_type = Column(String(32), nullable=False)      # "rating" или "physical"
    reward_value = Column(String(128), nullable=False)     # Приз
    winners_count = Column(Integer, default=1)            # Места
    condition_type = Column(String(32), nullable=False)   # "combo"
    condition_value = Column(String(128), nullable=False)  # "title_id:ticket_id"
    
    # Новые поля для планировщика времени
    announce_at = Column(DateTime, nullable=False)        # Время публикации требований
    finalize_at = Column(DateTime, nullable=False)        # Время автоматического финала
    status = Column(String(32), default="created")        # "created", "announced", "finished"
    created_at = Column(DateTime, default=datetime.utcnow)


class PromoChannel(Base):
    """Модель партнерских каналов для обязательных подписок."""
    __tablename__ = "promo_channels"
    id = Column(BigInteger, primary_key=True)  # Telegram ID канала
    invite_link = Column(String(256), nullable=False)
    reward = Column(Integer, default=50)

class ChatConfig(Base):
    __tablename__ = "chats_config"
    id = Column(BigInteger, primary_key=True)
    title = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)
    invite_link = Column(String(256), nullable=True)

class SystemSettings(Base):
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True, default=1)
    chest_open_price = Column(Integer, default=0)
    chest_min_title_id = Column(Integer, default=1)
    chest_quiet_hours = Column(Integer, default=12)
    chest_random_hours = Column(Integer, default=12)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    source = Column(String(32), nullable=False)
    item_name = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False) # Хранит строковое значение OrderStatus
    delivery_data = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    message_length = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

