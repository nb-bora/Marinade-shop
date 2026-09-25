from fastapi import APIRouter
from app.api.v1 import (
    auth,
    users,
    subscriptions,
    transactions,
    restaurants,
    operators,
    payments,
    ros,
    reservations,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(subscriptions.router)
api_router.include_router(transactions.router)
api_router.include_router(restaurants.router)
api_router.include_router(operators.router)
api_router.include_router(payments.router)
api_router.include_router(ros.router)
api_router.include_router(reservations.router)
