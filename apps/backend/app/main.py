from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    routes_analysis,
    routes_admins,
    routes_audiences,
    routes_ai_performance,
    routes_auth,
    routes_broadcasts,
    routes_campaigns,
    routes_crm,
    routes_dashboard,
    routes_knowledge,
    routes_leads,
    routes_prompts,
    routes_public,
    routes_reports,
    routes_settings,
    routes_source_links,
    routes_telegram,
)
from app.core.config import settings
from app.core.logging import configure_logging
from app.bot.webhook import setup_telegram_webhook

configure_logging()

app = FastAPI(title="Bella Vladi Face Protocol API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(
        {
            *settings.cors_origins,
            settings.frontend_url,
            settings.public_app_url,
            "http://frontend",
            "http://frontend:80",
        }
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.storage_root().mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(settings.storage_root())), name="storage")

app.include_router(routes_auth.router)
app.include_router(routes_admins.router)
app.include_router(routes_crm.router)
app.include_router(routes_source_links.router)
app.include_router(routes_audiences.router)
app.include_router(routes_ai_performance.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_leads.router)
app.include_router(routes_analysis.router)
app.include_router(routes_reports.router)
app.include_router(routes_public.router)
app.include_router(routes_knowledge.router)
app.include_router(routes_prompts.router)
app.include_router(routes_broadcasts.router)
app.include_router(routes_campaigns.router)
app.include_router(routes_settings.router)
app.include_router(routes_telegram.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "bella-vladi-face-protocol"}


@app.on_event("startup")
async def configure_telegram_webhook() -> None:
    await setup_telegram_webhook()
