from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

import models  # noqa: F401  (registra las tablas)
from routes.__init__ import * 
from config.database import SessionLocal, engine
from utils.seed import load_seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with SessionLocal() as session:
        await load_seed(session)
    yield
    await engine.dispose()


app = FastAPI(title="Socrates API", lifespan=lifespan)

app.include_router(auth_router)

@app.get("/health")
async def health():
    return {"status": "ok"}