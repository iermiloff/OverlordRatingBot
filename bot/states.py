from aiogram.fsm.state import StatesGroup, State

class OrderCheckout(StatesGroup):
    waiting_for_delivery_data = State() # Ожидание ФИО и адреса доставки
