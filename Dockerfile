# ИСПОЛЬЗУЕМ СТАБИЛЬНЫЙ ОФИЦИАЛЬНЫЙ ОБРАЗ PYTHON
FROM python:3.11-slim

# НАСТРАИВАЕМ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ PYTHON ДЛЯ КОНТЕЙНЕРА
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ЗАДАЕМ РАБОЧУЮ ДИРЕКТОРИЮ ВНУТРИ КОНТЕЙНЕРА
WORKDIR /app

# УСТАНАВЛИВАЕМ СИСТЕМНЫЕ ЗАВИСИМОСТИ, НЕОБХОДИМЫЕ ДЛЯ СБОРКИ КРИПТОГРАФИИ И ДВИЖКОВ БД
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# КОПИРУЕМ requirements.txt ИЗ КОРНЯ ПРОЕКТА
COPY requirements.txt .

# УСТАНАВЛИВАЕМ ЗАВИСИМОСТИ PYTHON БЕЗ ИСПОЛЬЗОВАНИЯ КЭША СБОРКИ
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# КОПИРУЕМ ВСЕ ОСТАЛЬНЫЕ ФАЙЛЫ ПРОЕКТА В КОНТЕЙНЕР
COPY . .

# КОМАНДА ПО УМОЛЧАНИЮ ДЛЯ ЗАПУСКА ОСНОВНОГО ПРОЦЕССА БОТА
CMD ["python", "main.py"]
