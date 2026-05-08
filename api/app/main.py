import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.health import router as health_router
from app.routers.auth import router as auth_router
from app.routers.platforms import router as platforms_router
from app.routers.accounts import router as accounts_router
from app.routers.dashboard import router as dashboard_router
from app.routers.currencies import router as currencies_router
from app.routers.categories import router as categories_router
from app.routers.spending import router as spending_router
from app.routers.ingest import router as ingest_router
from app.routers.crypto import router as crypto_router
from app.routers.market_data import router as market_data_router
from app.routers.alerts import router as alerts_router
from app.routers.dividends import router as dividends_router
from app.routers.rag import router as rag_router
from app.routers.ai_sage import router as ai_sage_router
from app.routers.realtime import router as realtime_router
from app.crypto.scheduler import start_scheduler
from app.market_data.scheduler import start_scheduler as start_market_scheduler
from app.services.ai_sage import prune_expired_ai_sage_chats




app = FastAPI(title="CapitalOS API", version="0.1.0")

_DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


def _resolve_cors_origins(raw_origins: str) -> list[str]:
    initial = [o.strip() for o in raw_origins.split(",") if o.strip()]
    if not initial:
        return list(_DEFAULT_CORS_ORIGINS)

    resolved = set(initial)
    for origin in initial:
        if origin.startswith("http://localhost:"):
            resolved.add(origin.replace("http://localhost:", "http://127.0.0.1:", 1))
        if origin.startswith("http://127.0.0.1:"):
            resolved.add(origin.replace("http://127.0.0.1:", "http://localhost:", 1))
    return sorted(resolved)


cors_origins = os.getenv("CORS_ORIGINS", "")
origins = _resolve_cors_origins(cors_origins)
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(platforms_router)
app.include_router(accounts_router)
app.include_router(dashboard_router)
app.include_router(currencies_router)
app.include_router(categories_router)
app.include_router(spending_router)
app.include_router(ingest_router)
app.include_router(crypto_router)
app.include_router(market_data_router)
app.include_router(alerts_router)
app.include_router(dividends_router)
app.include_router(rag_router)
app.include_router(ai_sage_router)
app.include_router(realtime_router)


def _schedule_alerts_pruning() -> None:
    """Schedule a daily background job to prune expired realtime_events (6-month retention)."""
    import logging
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.db.session import SessionLocal
    from app.services.alerts import prune_old_realtime_events

    log = logging.getLogger("capitalos.alerts.pruning")

    def _run_prune() -> None:
        db = SessionLocal()
        try:
            deleted = prune_old_realtime_events(db)
            log.info("Daily pruning complete: deleted=%d", deleted)
        except Exception:
            log.exception("Daily alerts pruning failed")
        finally:
            db.close()

    scheduler = BackgroundScheduler()
    scheduler.add_job(_run_prune, "interval", hours=24, id="alerts_prune_daily")
    scheduler.start()
    log.info("Alerts pruning scheduler started (interval=24h, retention_days=180)")


def _schedule_ai_sage_pruning() -> None:
    import logging
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.db.session import SessionLocal

    log = logging.getLogger("capitalos.ai_sage.pruning")

    def _run_prune() -> None:
        db = SessionLocal()
        try:
            deleted = prune_expired_ai_sage_chats(db)
            log.info("Daily AI Sage pruning complete: deleted=%d", deleted)
        except Exception:
            log.exception("Daily AI Sage pruning failed")
        finally:
            db.close()

    scheduler = BackgroundScheduler()
    scheduler.add_job(_run_prune, "interval", hours=24, id="ai_sage_prune_daily")
    scheduler.start()
    log.info("AI Sage pruning scheduler started (interval=24h, retention_days=365)")


@app.on_event("startup")
def _start_schedulers():
    start_scheduler()
    start_market_scheduler()
    _schedule_alerts_pruning()
    _schedule_ai_sage_pruning()
