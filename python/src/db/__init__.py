"""
Database persistence layer.

Provides:
  - get_db: FastAPI dependency for AsyncSession
  - get_cache: FastAPI dependency for Redis
  - create_db_and_tables: auto-create tables on startup
  - new_db_session: context manager for standalone DB access
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/meeting_assistant",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 延迟初始化，避免模块导入时即连接数据库
_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            DATABASE_URL, echo=False, pool_size=5, max_overflow=10
        )
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            _get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


@asynccontextmanager
async def new_db_session():
    """创建一个新的数据库会话（用于 WebSocket handler 等非 FastAPI Depends 场景）。"""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：每个请求一个数据库会话。"""
    async with new_db_session() as session:
        yield session


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
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
