from aiogram import Router

# Импортируем только живые и актуальные роутеры Беты
from .common import router as common_router
from .user_lk import router as user_lk_router
from .shop_user import router as shop_user_router
from .user_tasks import router as user_tasks_router
from .user_inventory import router as user_inventory_router
from .manager_users import router as manager_users_router
from .manager_shop import router as manager_shop_router
from .manager_antifraud import router as manager_antifraud_router
from .manager_activities import router as manager_activities_router
from .manager_giveaways import router as manager_giveaways_router
from .manager_settings import router as manager_settings_router
from .chat_activity import router as chat_activity_router
from .manager_custom_chests import router as custom_chests_router

def get_main_router() -> Router:
    """Собирает все роутеры проекта в единую иерархическую цепь."""
    main_router = Router(name="main_router")
    
    # Подключаем роутеры в строгом порядке приоритета
    main_router.include_router(common_router)
    main_router.include_router(user_lk_router)
    main_router.include_router(shop_user_router)
    main_router.include_router(user_tasks_router)
    main_router.include_router(user_inventory_router)
    main_router.include_router(manager_users_router)
    main_router.include_router(manager_shop_router)
    main_router.include_router(manager_antifraud_router)
    main_router.include_router(manager_activities_router)
    main_router.include_router(manager_giveaways_router)
    main_router.include_router(manager_settings_router)
    main_router.include_router(custom_chests_router)
    
    # Хэндлер активности чатов — строго в самый конец цепочки
    main_router.include_router(chat_activity_router)
    
    return main_router
