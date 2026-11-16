"""Interview Assistant SaaS API — FastAPI app entrypoint.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.routers import admin, ai, auth, plans, subscriptions, webhooks
from app.seed import seed_plans


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_plans(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Interview Assistant SaaS API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(plans.router)
app.include_router(subscriptions.router)
app.include_router(ai.router)
app.include_router(ai.session_router)
app.include_router(admin.router)
app.include_router(webhooks.router)
