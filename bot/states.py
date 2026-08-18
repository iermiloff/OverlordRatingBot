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

# ✅ ДОБАВЛЕНО: Группа состояний для создания карточки ShopItem
class ManagerShopItemSetup(StatesGroup):
    waiting_for_name = State()
    waiting_for_description = State()
    waiting_for_price = State()
    waiting_for_platform = State()
    waiting_for_image = State()

# ✅ ДОБАВЛЕНО: Группа состояний для заправки серийников/мерча на склад
class ManagerStockLoad(StatesGroup):
    waiting_for_units = State()

# ✅ ДОБАВЛЕНО: Группа состояний для вывода товаров на витрину
class ManagerShowcasePush(StatesGroup):
    waiting_for_count = State()

# ✅ ДОБАВЛЕНО: Группа состояний для оформления покупки пользователем
class UserPurchaseSetup(StatesGroup):
    waiting_for_delivery = State()
    waiting_for_confirm = State()

