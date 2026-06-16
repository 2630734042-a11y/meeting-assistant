"""
Database persistence layer.

Provides:
  - get_db: FastAPI dependency for AsyncSession
  - get_cache: FastAPI dependency for Redis
  - create_db_and_tables: auto-create tables on startup
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/meeting_assistant",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# SQLAlchemy 异步引擎（echo=False 生产环境）
engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)

# 异步 Session 工厂
async_session_factory = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：每个请求一个数据库会话。"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_cache() -> Redis:
    """FastAPI 依赖注入：Redis 连接。

    使用异步 Redis（redis.asyncio），兼容 FastAPI async handler。
    """
    return Redis.from_url(REDIS_URL, decode_responses=True)


async def create_db_and_tables() -> None:
    """启动时自动建表（仅 dev 环境使用，生产应使用 Alembic 迁移）。"""
    from src.db.models import (  # noqa: F401  # 确保表注册到 SQLModel.metadata
        Meeting,
        MeetingTranscript,
        MeetingSummaryModel,
        MeetingActionItemModel,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
