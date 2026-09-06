from fastapi import APIRouter

from app.api.v1 import agent, approval, execution, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(agent.router)
api_router.include_router(approval.router)
api_router.include_router(execution.router)
