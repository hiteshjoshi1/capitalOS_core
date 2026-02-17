import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.health import router as health_router
from app.routers.platforms import router as platforms_router
from app.routers.accounts import router as accounts_router
from app.routers.dashboard import router as dashboard_router
from app.routers.currencies import router as currencies_router
from app.routers.spending import router as spending_router




app = FastAPI(title="CapitalOS API", version="0.1.0")

cors_origins = os.getenv("CORS_ORIGINS", "")
origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health_router)
app.include_router(platforms_router)
app.include_router(accounts_router)
app.include_router(dashboard_router)
app.include_router(currencies_router)
app.include_router(spending_router)
