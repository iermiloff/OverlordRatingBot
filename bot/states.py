from aiogram.fsm.state import State, StatesGroup

class ManagerChestSettings(StatesGroup):
    waiting_for_quiet_hours = State()
    waiting_for_random_hours = State()
    waiting_for_chest_price = State()
    waiting_for_chest_min_title = State()

class ManagerActivitySetup(StatesGroup):
    waiting_for_reward_type = State()
    waiting_for_reward_value = State()
    waiting_for_reward_weight = State()

class ManagerCustomChestSetup(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_media = State()

class ManagerCustomRewardSetup(StatesGroup):
    waiting_for_type = State()
    waiting_for_value = State()
    waiting_for_weight = State()
    waiting_for_next_decision = State()

class ManagerShopItemSetup(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_platform = State()
    waiting_for_image = State()

class ManagerStockLoad(StatesGroup):
    waiting_for_units = State()

class ManagerShowcasePush(StatesGroup):
    waiting_for_count = State()

class UserPurchaseSetup(StatesGroup):
    waiting_for_delivery = State()
    waiting_for_confirm = State()

class ManagerGiveawaySetup(StatesGroup):
    waiting_for_type = State()
    waiting_for_value = State()
    waiting_for_winners = State()
    waiting_for_condition_type = State()  # Развилка: по Билету или по Титулу
    waiting_for_title = State()           # Выбор квалификационного ранга
    waiting_for_ticket = State()          # Выбор лотерейного билета из магазина
    waiting_for_announce_time = State()   # Дата и время публикации анонса
    waiting_for_finalize_time = State()   # Дата и время подведения итогов

class ManagerSettingsPromo(StatesGroup):
    waiting_for_channel_id = State()
    waiting_for_channel_name = State()
    waiting_for_invite_link = State()
    waiting_for_task_reward = State()

class ManagerUserWalletEdit(StatesGroup):
    waiting_for_balance_delta = State() 
