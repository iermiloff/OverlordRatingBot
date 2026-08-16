from aiogram.fsm.state import StatesGroup, State

class OrderCheckout(StatesGroup):
    waiting_for_delivery_data = State() # Ожидание ФИО и адреса доставки

class ManagerUserActions(StatesGroup):
    waiting_for_rating_amount = State()  # Ожидание ввода числа для изменения баланса
