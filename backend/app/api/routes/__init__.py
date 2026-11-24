from fastapi import APIRouter

from app.api.routes import alerts, chat, connectors, data, demo, health, plant, sessions, twin, users, utilities

api_router = APIRouter(prefix="/api")
for module in (health, users, sessions, chat, data, utilities, alerts, twin, plant, connectors, demo):
    api_router.include_router(module.router)
