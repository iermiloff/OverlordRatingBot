from aiogram.fsm.state import StatesGroup, State

class OrderCheckout(StatesGroup):
    waiting_for_delivery_data = State() # Ожидание ФИО и адреса доставки

class ManagerUserActions(StatesGroup):
    waiting_for_rating_amount = State()  # Ожидание ввода числа для изменения баланса

class ManagerShopCreate(StatesGroup):
    waiting_for_name = State()         # Ожидание ввода названия товара
    waiting_for_description = State()  # Ожидание описания товара
    waiting_for_price = State()        # Ожидание стоимости

class ManagerActivitySetup(StatesGroup):
    waiting_for_reward_type = State()   # Выбор типа: "rating" или "physical"
    waiting_for_reward_value = State()  # Количество поинтов или название мерча
    waiting_for_reward_weight = State() # Вес/Шанс выпадения (дробное число)
