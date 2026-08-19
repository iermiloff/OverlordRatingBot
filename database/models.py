from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, 
    Boolean, Float, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class PromoChannel(Base):
    """Модель отслеживания обязательных каналов подписки (Telegram/Discord)."""
    __tablename__ = "promo_channels"
    
    id = Column(BigInteger, primary_key=True) # ID канала или сервера
    name = Column(String(128), nullable=False)
    invite_link = Column(String(256), nullable=True)
    
    # ШЛЮЗ: 'tg' или 'discord'
    platform = Column(String(32), default="tg", nullable=False)
    is_required = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class User(Base):
    """Модель профиля участника кроссплатформенной экосистемы."""
    __tablename__ = "users"
    
    tg_id = Column(BigInteger, primary_key=True) # ID в Telegram
    discord_id = Column(BigInteger, nullable=True) # Изоляция под Discord!
    
    username = Column(String(64), nullable=True)
    full_name = Column(String(128), nullable=False)
    
    current_rating = Column(Integer, default=0)    # Доступный баланс
    lifetime_rating = Column(Integer, default=0)   # Исторический опыт
    timezone = Column(String(32), default="UTC", nullable=False) 
    referrer_id = Column(BigInteger, nullable=True)
    referred_users_count = Column(Integer, default=0, nullable=False)
    is_suspicious = Column(Boolean, default=False) # Антифрод
    antifraud_reason = Column(String(256), nullable=True)
    is_banned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с инвентарем (купленными уникальными единицами)
    owned_units = relationship("StockUnit", back_populates="owner")

class ShopItem(Base):
    """Мета-карточка товара/мерча в No-Code магазине."""
    __tablename__ = "shop_items"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Integer, nullable=False)
    image_url = Column(String(256), nullable=True)
    
    # Категории товара
    is_ticket = Column(Boolean, default=False)     # Лотерейный билет
    
    # КРОССПЛАТФОРМЕННЫЙ ШЛЮЗ: где продается товар? ('all', 'tg', 'discord')
    platform_target = Column(String(32), default="all", nullable=False)
    
    is_deleted = Column(Boolean, default=False)    # Мягкое удаление
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с конкретными физическими единицами на складе
    units = relationship(
        "StockUnit", 
        back_populates="item", 
        cascade="all, delete-orphan"
    )

class StockUnit(Base):
    """Поштучный учет каждой единицы товара (Склад / Витрина / Инвентарь)."""
    __tablename__ = "stock_units"
    
    id = Column(Integer, primary_key=True, autoincrement=True) # Цифровой ID вещи!
    item_id = Column(Integer, ForeignKey("shop_items.id", ondelete="CASCADE"), nullable=False)
    
    # Для промокодов/ключей — секретный текст. Для мерча — серийник или NULL
    serial_or_promo = Column(String(512), nullable=True) 
    
    # Статусы: 'stock' (склад), 'showcase' (витрина), 'sold' (выдано/инвентарь), 'won' (лотерея)
    status = Column(String(32), default="stock", nullable=False)
    
    # Кросплатформенный владелец: связываем по первичному ключу users (tg_id)
    owner_id = Column(BigInteger, ForeignKey("users.tg_id", ondelete="SET NULL"), nullable=True)
    
    # ШЛЮЗ: Через какую платформу была куплена/выиграна вещь? ('tg', 'discord', 'giveaway')
    purchase_source = Column(String(32), default="tg", nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    item = relationship("ShopItem", back_populates="units")
    owner = relationship("User", back_populates="owned_units")

class ChestReward(Base):
    """Пул наград автоматического сундука активности."""
    __tablename__ = "chest_rewards"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reward_type = Column(String(32), nullable=False) # 'rating' или 'item'
    value = Column(String(256), nullable=False)      # Число монет или ID ShopItem!
    weight = Column(Float, default=1.0)

class CustomChest(Base):
    """Мета-карточка кастомного сундука ручного заброса."""
    __tablename__ = "custom_chests"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=False)
    media_url = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    open_price = Column(Integer, default=0, nullable=True)
    min_title_id = Column(Integer, default=1, nullable=True)
    required_item_id = Column(Integer, ForeignKey("shop_items.id"), nullable=True) 
    rewards = relationship("CustomChestReward", back_populates="chest", cascade="all, delete-orphan")

class CustomChestReward(Base):
    """Пул наград конкретного кастомного сундука."""
    __tablename__ = "custom_chest_rewards"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chest_id = Column(Integer, ForeignKey("custom_chests.id", ondelete="CASCADE"), nullable=False)
    reward_type = Column(String(32), nullable=False) # 'rating' или 'item' (из ShopItem)
    value = Column(String(256), nullable=False)      
    weight = Column(Float, default=1.0)
    
    chest = relationship("CustomChest", back_populates="rewards")

class Giveaway(Base):
    """Автоматические лотереи и розыгрыши."""
    __tablename__ = "giveaways"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reward_type = Column(String(32), nullable=False) # 'rating' или 'item' (из ShopItem)
    reward_value = Column(String(128), nullable=False)
    winners_count = Column(Integer, nullable=False)
    condition_type = Column(String(32), default="free", nullable=False)
    condition_value = Column(String(64), nullable=True) # ID билета, если тип 'ticket'
    min_title_id = Column(Integer, default=1, nullable=False)
    announce_at = Column(DateTime, nullable=False)
    finalize_at = Column(DateTime, nullable=False)
    status = Column(String(32), default="created", nullable=False) # 'created', 'announced', 'finished'

class ChatConfig(Base):
    """Конфигурация подключенных чатов и серверов."""
    __tablename__ = "chat_configs"
    
    id = Column(BigInteger, primary_key=True) # Идентификатор чата (TG ID или Discord Guild ID)
    title = Column(String(128), nullable=False)
    invite_link = Column(String(256), nullable=True) 
    
    # ПЛАТФОРМА ЧАТА: 'tg' или 'discord'
    platform = Column(String(32), default="tg", nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ActivityLog(Base):
    """Лог сообщений для кроссплатформенного скоринга опыта."""
    __tablename__ = "activity_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False) # TG ID или Discord User ID
    chat_id = Column(BigInteger, nullable=False)
    platform = Column(String(32), default="tg", nullable=False) # 'tg' / 'discord'
    message_length = Column(Integer, default=0)
    earned_rating = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class SystemSettings(Base):
    """Глобальные No-Code лимиты автоматических сундуков."""
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True)
    chest_open_price = Column(Integer, default=0)
    chest_min_title_id = Column(Integer, default=1)
    chest_quiet_hours = Column(Integer, default=15)  # Теперь это МИНУТЫ сна
    chest_random_hours = Column(Integer, default=30) # Теперь это МИНУТЫ рандома
