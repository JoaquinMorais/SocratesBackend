from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from config.settings import settings

engine = create_async_engine(settings.DATABASE_URL)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        yield session


db_dependency = Annotated[AsyncSession, Depends(get_session)]