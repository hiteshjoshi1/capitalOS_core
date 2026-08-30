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
from app.routers.portfolio import router as portfolio_router
from app.routers.alerts import router as alerts_router
from app.routers.dividends import router as dividends_router
from app.routers.realtime import router as realtime_router
from app.core.logging import RequestIdMiddleware, configure_logging
from app.crypto.scheduler import start_scheduler
from app.market_data.scheduler import start_scheduler as start_market_scheduler
from app.portfolio.scheduler import start_scheduler as start_portfolio_scheduler




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
app.add_middleware(RequestIdMiddleware)

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
app.include_router(portfolio_router)
app.include_router(alerts_router)
app.include_router(dividends_router)
app.include_router(realtime_router)


@app.on_event("startup")
def _start_schedulers():
    configure_logging()
    start_scheduler()
    start_market_scheduler()
    start_portfolio_scheduler()
