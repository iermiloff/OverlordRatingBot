import os
from typing import List, Dict
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class TitleInfo(BaseModel):
    id: int
    name: str
    min_rating: int

class Settings(BaseSettings):
    # Автоматически ищет переменные в .env файле
    model_config = SettingsConfigDict(
        env_file='.env', 
        env_file_encoding='utf-8', 
        extra='ignore'
    )

    # Технические настройки
    BOT_TOKEN: str
    DATABASE_URL: str
    MANAGERS_IDS: str  # Принимаем как строку, ниже распарсим в список

    # Брендирование
    BOT_NAME: str
    CURRENCY_NAME: str
    CURRENCY_EMOJI: str
    SUPPORT_USERNAME: str

    # Экономика
    REF_REWARD_RATING: int
    REF_TARGET_RATING: int
    RATING_PER_MESSAGE: int
    COOLDOWN_MESSAGE_SEC: int

    # Конфигурация титулов
    TITLES_CONFIG: str

    # Анти-фрод
    MAX_MESSAGES_PER_DAY: int
    MIN_MESSAGE_LENGTH_FOR_RATING: int

    @property
    def managers_list(self) -> List[int]:
        """Возвращает список ID менеджеров в формате integer."""
        if not self.MANAGERS_IDS:
            return []
        return [int(m.strip()) for m in self.MANAGERS_IDS.split(",") if m.strip().isdigit()]

    @property
    def parsed_titles(self) -> Dict[int, TitleInfo]:
        """
        Парсит строку вроде '1:Новичок:0;2:Активист:100' 
        в структурированный словарь для быстрой проверки.
        """
        titles_dict = {}
        if not self.TITLES_CONFIG:
            return titles_dict
            
        raw_chunks = self.TITLES_CONFIG.split(";")
        for chunk in raw_chunks:
            if not chunk.strip():
                continue
            parts = chunk.split(":")
            if len(parts) == 3:
                t_id, t_name, t_rating = parts
                titles_dict[int(t_id)] = TitleInfo(
                    id=int(t_id),
                    name=t_name.strip(),
                    min_rating=int(t_rating)
                )
        return titles_dict

# Инициализируем настройки для импорта в другие модули
settings = Settings()
