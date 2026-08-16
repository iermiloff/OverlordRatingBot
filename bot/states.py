from aiogram.fsm.state import StatesGroup, State

class OrderCheckout(StatesGroup):
    waiting_for_delivery_data = State() # Ожидание ФИО и адреса доставки

class ManagerUserActions(StatesGroup):
    waiting_for_rating_amount = State()  # Ожидание ввода числа для изменения баланса

class ManagerShop(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_media = State()
    waiting_for_type = State()

class ManagerActivitySetup(StatesGroup):
    waiting_for_reward_type = State()   # Выбор типа: "rating" или "physical"
    waiting_for_reward_value = State()  # Количество поинтов или название мерча
    waiting_for_reward_weight = State() # Вес/Шанс выпадения (дробное число)

class ManagerSettingsPromo(StatesGroup):
    waiting_for_channel_id = State()     # Ожидание ID канала (например, -100123456789)
    waiting_for_invite_link = State()    # Ожидание инвайт-ссылки
    waiting_for_task_reward = State()    # Ожидание суммы награды за подписку
    
class ManagerChestSettings(StatesGroup):
    waiting_for_chest_price = State()
    waiting_for_chest_title = State()
    waiting_for_quiet_hours = State()   # Шаг 1: Время сна
    waiting_for_random_hours = State()  # Шаг 2: Диапазон рандома
    
class ManagerGiveawaySetup(StatesGroup):
    waiting_for_reward_type = State()
    waiting_for_reward_value = State()
    waiting_for_winners_count = State()
    waiting_for_condition_type = State()
    waiting_for_condition_value = State()
    waiting_for_announce_time = State()  # Шаг для времени анонса
    waiting_for_finalize_time = State()  # Шаг для времени финала
