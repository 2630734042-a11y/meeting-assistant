# 数据库持久化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将会议数据从 Python 内存字典迁移到 PostgreSQL + Redis 双层存储，前端历史记录从 localStorage 迁移到服务端 API。

**Architecture:** SQLModel 建 4 张表（meetings / meeting_transcripts / meeting_summaries / meeting_action_items），通过 `src/db/repository.py` 封装 CRUD + Redis 缓存逻辑，`server.py` 通过 FastAPI `Depends` 注入数据库会话。Redis 纯做缓存（读命中直接返回，写时删 cache key），不可用时自动回退 PostgreSQL 直查。

**Tech Stack:** SQLModel, asyncpg, Redis (redis-py), FastAPI Depends

---

### Task 1: 环境准备 — 依赖 + 配置

**Files:**
- Modify: `python/pyproject.toml` (add 3 deps)
- Modify: `.env.example` (update DATABASE_URL to async)

- [ ] **Step 1: 新增 Python 依赖**

在 `python/pyproject.toml` 的 `dependencies` 列表中追加 3 行：

```toml
"sqlmodel>=0.0.22",
"asyncpg>=0.30.0",
"redis>=5.2.0",
```

在 `python/pyproject.toml` 的 `dev` optional-dependencies 中追加：

```toml
"pytest-asyncio>=0.24",
```

确认 `sqlalchemy>=2.0.0` 已存在（SQLModel 依赖它），无需重复添加。

- [ ] **Step 2: 更新 .env.example 数据库 URL 为异步驱动**

将 `.env.example` 中：

```bash
DATABASE_URL=postgresql://postgres:password@localhost:5432/meeting_assistant
```

改为：

```bash
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/meeting_assistant
```

同步更新 `.env` 文件中的 `DATABASE_URL`（如果有的话）。

- [ ] **Step 3: 安装新依赖**

```bash
cd python && pip install -e ".[dev]"
```

- [ ] **Step 4: 验证安装**

```bash
python -c "import sqlmodel; import asyncpg; import redis; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add python/pyproject.toml .env.example .env
git commit -m "chore: add SQLModel + asyncpg + redis deps, switch DATABASE_URL to asyncpg"
```

---

### Task 2: 创建数据库表模型

**Files:**
- Create: `python/src/db/__init__.py`
- Create: `python/src/db/models.py`

- [ ] **Step 1: 创建 `__init__.py`**（空文件，先让包存在）

```bash
echo '"""Database persistence layer."""' > python/src/db/__init__.py
```

- [ ] **Step 2: 创建 `python/src/db/models.py`**

```python
"""
SQLModel 数据库表模型

与 schemas.py (Pydantic) 共存——schemas 用于 API 序列化/Agent 通信，
这里的模型用于 PostgreSQL 持久化。两者通过 .model_dump() 互转。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


# ============================================================
# Meeting — 会议主表
# ============================================================

class Meeting(SQLModel, table=True):
    __tablename__ = "meetings"

    id: str = Field(primary_key=True)
    title: Optional[str] = None
    status: str = "created"                    # MeetingStatus
    source: str = "live"                       # "live" | "upload"
    duration_seconds: float = 0.0
    segment_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================
# MeetingTranscript — 转写段 (1:N)
# ============================================================

class MeetingTranscript(SQLModel, table=True):
    __tablename__ = "meeting_transcripts"

    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: str = Field(foreign_key="meetings.id", index=True)
    seq: int                                    # 顺序号
    speaker: str
    text: str
    start: float                                # 绝对秒
    end: float
    confidence: float = 0.0


# ============================================================
# MeetingSummary — 会议纪要 (1:1)
# ============================================================

class MeetingSummaryModel(SQLModel, table=True):
    """命名加 Model 后缀，避免与 schemas.py 的 MeetingSummary 冲突"""

    __tablename__ = "meeting_summaries"

    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: str = Field(foreign_key="meetings.id", unique=True)
    title: str = ""
    topics: str = ""                            # JSON string of TopicSummary[]
    decisions: str = ""
    conclusions: str = ""


# ============================================================
# MeetingActionItem — 待办事项 (1:N)
# ============================================================

class MeetingActionItemModel(SQLModel, table=True):
    """命名加 Model 后缀，避免与 schemas.py 的 ActionItem 冲突"""

    __tablename__ = "meeting_action_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_id: str = Field(foreign_key="meetings.id", index=True)
    task: str
    owner: str
    priority: str = "medium"                    # low / medium / high / urgent
    due_date: Optional[str] = None
    review_status: str = "pending"              # pending / approved / rejected
    jira_key: Optional[str] = None
    feishu_task_id: Optional[str] = None
```

- [ ] **Step 3: 验证模型可导入**

```bash
cd python && python -c "from src.db.models import Meeting, MeetingTranscript, MeetingSummaryModel, MeetingActionItemModel; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add python/src/db/__init__.py python/src/db/models.py
git commit -m "feat: add SQLModel table definitions (4 tables)"
```

---

### Task 3: 创建数据库连接层

**Files:**
- Modify: `python/src/db/__init__.py`

- [ ] **Step 1: 重写 `python/src/db/__init__.py`**

```python
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
```

- [ ] **Step 2: 验证连接层可导入**

```bash
cd python && python -c "from src.db import get_db, get_cache, create_db_and_tables; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add python/src/db/__init__.py
git commit -m "feat: add async DB engine, session factory, and Redis connection"
```

---

### Task 4: 创建 Repository 层

**Files:**
- Create: `python/src/db/repository.py`

- [ ] **Step 1: 创建 `python/src/db/repository.py`**

```python
"""
MeetingRepository — 会议数据 CRUD + Redis 缓存

读: Redis hit → 返回 | miss → PostgreSQL → 回写缓存
写: PostgreSQL → 删 Redis 对应 key
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Meeting,
    MeetingTranscript,
    MeetingSummaryModel,
    MeetingActionItemModel,
)

# Cache TTL constants
TTL_MEETING = 300       # 5 min
TTL_TRANSCRIPT = 300    # 5 min
TTL_LIST = 120          # 2 min


class MeetingRepository:
    """会议数据仓库，封装 PostgreSQL CRUD + Redis 缓存。"""

    def __init__(self, db: AsyncSession, cache: Redis | None = None):
        self._db = db
        self._cache = cache

    # ================================================================
    # Meeting CRUD
    # ================================================================

    async def create_meeting(
        self,
        meeting_id: str,
        title: str | None = None,
        source: str = "live",
        status: str = "created",
    ) -> Meeting:
        """创建会议记录。"""
        meeting = Meeting(
            id=meeting_id,
            title=title,
            source=source,
            status=status,
        )
        self._db.add(meeting)
        await self._db.flush()
        # 删列表缓存
        await self._invalidate_list_cache()
        logger.info(f"[DB] Meeting created: {meeting_id}")
        return meeting

    async def get_meeting(self, meeting_id: str) -> Meeting | None:
        """获取会议详情（优先读缓存）。"""
        cached = await self._cache_get(f"meeting:{meeting_id}")
        if cached:
            logger.debug(f"[CACHE] meeting:{meeting_id} hit")
            return Meeting.model_validate(cached)

        result = await self._db.execute(
            select(Meeting).where(Meeting.id == meeting_id)
        )
        meeting = result.scalar_one_or_none()
        if meeting:
            await self._cache_set(f"meeting:{meeting_id}", meeting.model_dump())
        return meeting

    async def list_meetings(
        self, page: int = 1, size: int = 20
    ) -> tuple[list[Meeting], int]:
        """分页查询会议列表（优先读缓存）。"""
        cache_key = f"meeting:list:page:{page}"
        cached = await self._cache_get(cache_key)
        if cached:
            logger.debug(f"[CACHE] {cache_key} hit")
            data = json.loads(cached) if isinstance(cached, str) else cached
            return [Meeting.model_validate(m) for m in data["items"]], data["total"]

        # 查询总数
        count_result = await self._db.execute(
            select(func.count()).select_from(Meeting)
        )
        total = count_result.scalar_one()

        # 查询当前页
        offset = (page - 1) * size
        result = await self._db.execute(
            select(Meeting)
            .order_by(Meeting.created_at.desc())
            .offset(offset)
            .limit(size)
        )
        meetings = result.scalars().all()

        payload = {
            "items": [m.model_dump() for m in meetings],
            "total": total,
        }
        await self._cache_set(cache_key, json.dumps(payload, default=str), ttl=TTL_LIST)
        return list(meetings), total

    async def update_meeting(self, meeting_id: str, **kwargs) -> Meeting | None:
        """更新会议字段。"""
        meeting = await self.get_meeting(meeting_id)
        if not meeting:
            return None
        for key, val in kwargs.items():
            if hasattr(meeting, key):
                setattr(meeting, key, val)
        meeting.updated_at = datetime.utcnow()
        self._db.add(meeting)
        await self._db.flush()
        # 刷新缓存
        await self._cache_delete(f"meeting:{meeting_id}")
        await self._cache_set(f"meeting:{meeting_id}", meeting.model_dump())
        await self._invalidate_list_cache()
        return meeting

    async def delete_meeting(self, meeting_id: str) -> bool:
        """删除会议及所有关联数据。"""
        # 删除关联表
        for model in [MeetingActionItemModel, MeetingSummaryModel, MeetingTranscript]:
            await self._db.execute(
                sa_delete(model).where(model.meeting_id == meeting_id)
            )
        # 删除主表
        result = await self._db.execute(
            sa_delete(Meeting).where(Meeting.id == meeting_id)
        )
        await self._db.flush()
        # 清缓存
        await self._cache_delete(f"meeting:{meeting_id}")
        await self._cache_delete(f"meeting:{meeting_id}:transcript")
        await self._invalidate_list_cache()
        deleted = result.rowcount > 0
        if deleted:
            logger.info(f"[DB] Meeting deleted: {meeting_id}")
        return deleted

    # ================================================================
    # Transcript
    # ================================================================

    async def save_transcript(
        self, meeting_id: str, segments: list[dict]
    ) -> list[MeetingTranscript]:
        """批量写入转写段（先删旧数据再插入）。"""
        # 删除旧数据
        await self._db.execute(
            sa_delete(MeetingTranscript).where(
                MeetingTranscript.meeting_id == meeting_id
            )
        )
        # 批量插入
        rows = []
        for i, seg in enumerate(segments):
            row = MeetingTranscript(
                meeting_id=meeting_id,
                seq=i,
                speaker=seg.get("speaker", "Unknown"),
                text=seg.get("text", ""),
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
                confidence=seg.get("confidence", 0.0),
            )
            self._db.add(row)
            rows.append(row)
        await self._db.flush()
        # 更新缓存
        await self._cache_set(
            f"meeting:{meeting_id}:transcript",
            json.dumps([r.model_dump() for r in rows], default=str),
        )
        return rows

    async def get_transcript(self, meeting_id: str) -> list[MeetingTranscript]:
        """获取转写段列表。"""
        cache_key = f"meeting:{meeting_id}:transcript"
        cached = await self._cache_get(cache_key)
        if cached:
            data = json.loads(cached) if isinstance(cached, str) else cached
            return [MeetingTranscript.model_validate(s) for s in data]

        result = await self._db.execute(
            select(MeetingTranscript)
            .where(MeetingTranscript.meeting_id == meeting_id)
            .order_by(MeetingTranscript.seq)
        )
        rows = result.scalars().all()
        return list(rows)

    # ================================================================
    # Summary
    # ================================================================

    async def save_summary(self, meeting_id: str, summary: dict) -> MeetingSummaryModel:
        """保存/覆盖会议纪要。"""
        # 先删旧
        await self._db.execute(
            sa_delete(MeetingSummaryModel).where(
                MeetingSummaryModel.meeting_id == meeting_id
            )
        )
        row = MeetingSummaryModel(
            meeting_id=meeting_id,
            title=summary.get("title", ""),
            topics=json.dumps(summary.get("topics", []), ensure_ascii=False),
            decisions=summary.get("decisions", ""),
            conclusions=summary.get("conclusions", ""),
        )
        self._db.add(row)
        await self._db.flush()
        # meeting 缓存失效
        await self._cache_delete(f"meeting:{meeting_id}")
        return row

    async def get_summary(self, meeting_id: str) -> MeetingSummaryModel | None:
        result = await self._db.execute(
            select(MeetingSummaryModel).where(
                MeetingSummaryModel.meeting_id == meeting_id
            )
        )
        return result.scalar_one_or_none()

    # ================================================================
    # Action Items
    # ================================================================

    async def save_action_items(
        self, meeting_id: str, items: list[dict]
    ) -> list[MeetingActionItemModel]:
        """批量写入待办（先删旧再插入）。"""
        await self._db.execute(
            sa_delete(MeetingActionItemModel).where(
                MeetingActionItemModel.meeting_id == meeting_id
            )
        )
        rows = []
        for item in items:
            row = MeetingActionItemModel(
                meeting_id=meeting_id,
                task=item.get("task", ""),
                owner=item.get("owner", item.get("assignee", "Unknown")),
                priority=item.get("priority", "medium"),
                due_date=item.get("due_date", item.get("deadline")),
                review_status=item.get("review_status", "pending"),
                jira_key=item.get("jira_key"),
                feishu_task_id=item.get("feishu_task_id"),
            )
            self._db.add(row)
            rows.append(row)
        await self._db.flush()
        await self._cache_delete(f"meeting:{meeting_id}")
        return rows

    async def get_action_items(self, meeting_id: str) -> list[MeetingActionItemModel]:
        result = await self._db.execute(
            select(MeetingActionItemModel).where(
                MeetingActionItemModel.meeting_id == meeting_id
            )
        )
        return list(result.scalars().all())

    async def update_action_review(
        self, item_id: int, review_status: str
    ) -> MeetingActionItemModel | None:
        """更新单条待办的审核状态。"""
        result = await self._db.execute(
            select(MeetingActionItemModel).where(
                MeetingActionItemModel.id == item_id
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return None
        item.review_status = review_status
        self._db.add(item)
        await self._db.flush()
        await self._cache_delete(f"meeting:{item.meeting_id}")
        return item

    # ================================================================
    # Cache helpers
    # ================================================================

    async def _cache_get(self, key: str):
        if not self._cache:
            return None
        try:
            val = await self._cache.get(key)
            if val and isinstance(val, str):
                return json.loads(val)
            return val
        except Exception:
            return None

    async def _cache_set(self, key: str, value, ttl: int = TTL_MEETING) -> None:
        if not self._cache:
            return
        try:
            payload = json.dumps(value, default=str) if not isinstance(value, str) else value
            await self._cache.setex(key, ttl, payload)
        except Exception as e:
            logger.warning(f"[CACHE] set failed for {key}: {e}")

    async def _cache_delete(self, key: str) -> None:
        if not self._cache:
            return
        try:
            await self._cache.delete(key)
        except Exception:
            pass

    async def _invalidate_list_cache(self) -> None:
        """清除所有分页缓存（会议增删时调用）。"""
        if not self._cache:
            return
        try:
            # 简单实现：删前 10 页
            keys = [f"meeting:list:page:{p}" for p in range(1, 11)]
            for k in keys:
                await self._cache.delete(k)
        except Exception:
            pass
```

- [ ] **Step 2: 验证 Repository 可导入**

```bash
cd python && python -c "from src.db.repository import MeetingRepository; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add python/src/db/repository.py
git commit -m "feat: add MeetingRepository with CRUD + Redis cache layer"
```

---

### Task 5: 改造 server.py — 接入数据库

**Files:**
- Modify: `python/src/websocket/server.py`

- [ ] **Step 1: 添加 import 和启动事件**

在文件顶部的 import 区域追加：

```python
from ..db import get_db, get_cache, create_db_and_tables
from ..db.repository import MeetingRepository
```

在 `app = FastAPI(...)` 之后、`active_connections` 之前添加 startup 事件：

```python
@app.on_event("startup")
async def startup():
    await create_db_and_tables()
    logger.info("Database tables created/verified")
```

- [ ] **Step 2: 改造 `/api/v1/meeting/{meeting_id}/upload`**

将 `meeting_results[meeting_id] = result` 替换为写入数据库：

```python
# 原: meeting_results[meeting_id] = result
# 改为:
from ..db.repository import MeetingRepository
from ..db import get_db, get_cache
from fastapi import Depends
```

在 handler 中写 DB。先在函数签名加 `db`:

```python
@app.post("/api/v1/meeting/{meeting_id}/upload")
async def upload_audio(
    meeting_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
):
```

handler 末尾将 `meeting_results[meeting_id] = result` 替换为：

```python
    repo = MeetingRepository(db, cache)
    await repo.create_meeting(meeting_id, title=file.filename, source="upload", status="completed")

    transcript = result.get("transcript")
    if transcript:
        segs = transcript.model_dump().get("segments", []) if hasattr(transcript, "model_dump") else transcript.get("segments", [])
        await repo.save_transcript(meeting_id, segs)

    summary = result.get("summary")
    if summary:
        sd = summary.model_dump() if hasattr(summary, "model_dump") else summary
        await repo.save_summary(meeting_id, sd)

    actions = result.get("actions")
    if actions:
        ad = actions.model_dump() if hasattr(actions, "model_dump") else actions
        items = ad.get("action_items", []) if isinstance(ad, dict) else []
        if items:
            await repo.save_action_items(meeting_id, items)

    await repo.update_meeting(meeting_id, duration_seconds=(
        result.get("duration_seconds", 0)
        or (transcript.model_dump().get("duration_seconds", 0) if transcript and hasattr(transcript, "model_dump") else 0)
    ))
```

同样的模式应用于：
- `upload_video`（比照 upload 改造）
- `run_demo`（比照 upload 改造）
- `websocket_meeting` 中的 stop 和 demo 分支

对于实时会议 `websocket_live_meeting`，在 `session.run()` 之后写 DB：

```python
@app.websocket("/ws/live/{meeting_id}")
async def websocket_live_meeting(websocket: WebSocket, meeting_id: str):
    await websocket.accept()
    session = LiveSessionManager(meeting_id=meeting_id, websocket=websocket)
    try:
        await session.run()
        # 会议结束后写入 DB
        async with async_session_factory() as db:
            repo = MeetingRepository(db)
            await repo.create_meeting(
                meeting_id,
                title=f"实时会议 {meeting_id}",
                source="live",
                status="completed",
            )
            if session.final_transcript:
                segs = session.final_transcript.model_dump().get("segments", [])
                await repo.save_transcript(meeting_id, segs)
    except Exception as e:
        logger.error(f"Live session error: {meeting_id} - {e}")
```

- [ ] **Step 3: 改造现有查询端点**

下面所有 `meeting_results.get(meeting_id)` 替换为通过 `MeetingRepository` 查询：

| 端点 | 改动 |
|------|------|
| `GET /api/v1/meeting/{id}/transcript` | `repo.get_transcript(id)` |
| `GET /api/v1/meeting/{id}/summary` | `repo.get_summary(id)` + `repo.get_meeting(id)` |
| `GET /api/v1/meeting/{id}/actions` | `repo.get_action_items(id)` |
| `GET /api/v1/meeting/{id}/insights` | `repo.get_meeting(id)`（insight 暂存 meeting 字段，未来可扩展） |
| `GET /api/v1/meeting/{id}/report` | 组合 `get_transcript` + `get_summary` + `get_action_items` |
| `PUT /meeting/{id}/review` | `repo.update_action_review(item_id, status)` |
| `POST /meeting/{id}/resume` | 保留 `meeting_results` 用于 LangGraph checkpoint（checkpoint state 仍需内存） |

- [ ] **Step 4: 新增 3 个 REST 端点**

在 `server.py` 末尾（`StaticFiles mount` 之前）新增：

```python
@app.get("/api/v1/meetings")
async def list_meetings(
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
):
    """历史会议列表（分页）。"""
    repo = MeetingRepository(db, cache)
    meetings, total = await repo.list_meetings(page, size)
    return {
        "items": [
            {
                "id": m.id,
                "title": m.title,
                "status": m.status,
                "source": m.source,
                "duration_seconds": m.duration_seconds,
                "segment_count": m.segment_count,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in meetings
        ],
        "total": total,
        "page": page,
        "size": size,
    }


@app.get("/api/v1/meeting/{meeting_id}")
async def get_meeting_detail(
    meeting_id: str,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
):
    """获取会议完整详情。"""
    repo = MeetingRepository(db, cache)
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    transcript = await repo.get_transcript(meeting_id)
    summary = await repo.get_summary(meeting_id)
    actions = await repo.get_action_items(meeting_id)

    return {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status,
        "source": meeting.source,
        "duration_seconds": meeting.duration_seconds,
        "segment_count": meeting.segment_count,
        "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
        "transcript": {
            "segments": [
                {"speaker": s.speaker, "text": s.text, "start": s.start, "end": s.end, "confidence": s.confidence}
                for s in transcript
            ]
        } if transcript else None,
        "summary": summary.model_dump() if summary else None,
        "actions": {
            "action_items": [a.model_dump() for a in actions]
        } if actions else None,
    }


@app.delete("/api/v1/meeting/{meeting_id}")
async def delete_meeting(
    meeting_id: str,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
):
    """删除会议及所有关联数据。"""
    repo = MeetingRepository(db, cache)
    deleted = await repo.delete_meeting(meeting_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"status": "deleted", "meeting_id": meeting_id}
```

**注意**：handler 中所有 `from ..db import ...` 的 import 移到文件顶部统一管理。

- [ ] **Step 5: 处理 HITL review 端点改造**

`PUT /api/v1/meeting/{meeting_id}/actions/review` 中将内存更新替换为：

```python
    # ... 原有的 review 逻辑处理完后
    # 同步写 DB
    async with async_session_factory() as db:
        repo = MeetingRepository(db)
        for review in reviewed_items:
            item_id = review.get("id") or review.get("index")
            if item_id is not None:
                await repo.update_action_review(item_id, review.get("review_status", "reviewed"))
```

由于 `review_actions` handler 里已经有 `request: Request` 参数且没有 `Depends`，目前无法直接用 FastAPI 注入 `db`。采用创建独立 session 的方式绕过（如上面代码）。

- [ ] **Step 6: 验证——启动服务并查看 /docs**

```bash
cd python && python main.py
```

访问 `http://localhost:8000/docs`，确认可以看到新增的：
- `GET /api/v1/meetings`
- `GET /api/v1/meeting/{meeting_id}`
- `DELETE /api/v1/meeting/{meeting_id}`

- [ ] **Step 7: Commit**

```bash
git add python/src/websocket/server.py
git commit -m "feat: replace in-memory meeting_results with PostgreSQL + add 3 REST endpoints"
```

---

### Task 6: 前端 — 新增 API 函数

**Files:**
- Modify: `python/frontend/src/shared/api.ts`

- [ ] **Step 1: 在 `api` 对象中追加 3 个方法**

```typescript
  // ========== 历史记录 ==========

  listMeetings: (page = 1, size = 20) =>
    request<{ items: any[]; total: number; page: number; size: number }>(
      `/api/v1/meetings?page=${page}&size=${size}`
    ),

  getMeeting: (meetingId: string) =>
    request<any>(`/api/v1/meeting/${meetingId}`),

  deleteMeeting: (meetingId: string) =>
    request<{ status: string }>(`/api/v1/meeting/${meetingId}`, {
      method: 'DELETE',
    }),
```

- [ ] **Step 2: 验证——编译前端**

```bash
cd python/frontend && npm run build 2>&1 | tail -5
```

确认输出包含 `✓ built in`。

- [ ] **Step 3: Commit**

```bash
git add python/frontend/src/shared/api.ts python/static/
git commit -m "feat: add listMeetings, getMeeting, deleteMeeting API functions"
```

---

### Task 7: 前端 — 改造 HistoryView

**Files:**
- Modify: `python/frontend/src/views/HistoryView.vue`

- [ ] **Step 1: 重写 `HistoryView.vue`**

```vue
<template>
  <n-card title="📋 历史会议">
    <n-data-table
      :columns="columns"
      :data="meetings"
      :loading="loading"
      :pagination="pagination"
      @update:page="onPageChange"
      :row-props="(row: any) => ({ style: 'cursor: pointer', onClick: () => goToReport(row.id) })"
    >
      <template #empty>
        <n-empty description="暂无历史会议记录" />
      </template>
    </n-data-table>
  </n-card>
</template>

<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../shared/api'
import { NButton, NPopconfirm, NSpace, NTag } from 'naive-ui'

const router = useRouter()

const loading = ref(false)
const meetings = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const pagination = ref({
  page: 1,
  pageSize: 20,
  showSizePicker: false,
  itemCount: 0,
  prefix: (info: any) => `共 ${total.value} 条`,
})

async function fetchMeetings() {
  loading.value = true
  try {
    const res = await api.listMeetings(page.value, pageSize)
    meetings.value = res.items
    total.value = res.total
    pagination.value.itemCount = res.total
    pagination.value.page = page.value
  } catch (e) {
    console.error('Failed to fetch meetings:', e)
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  fetchMeetings()
}

function goToReport(id: string) {
  router.push(`/report/${id}`)
}

async function handleDelete(id: string) {
  await api.deleteMeeting(id)
  fetchMeetings()
}

const statusMap: Record<string, { type: 'default' | 'success' | 'warning' | 'error'; label: string }> = {
  completed: { type: 'success', label: '已完成' },
  created: { type: 'default', label: '待处理' },
  transcribing: { type: 'warning', label: '处理中' },
  failed: { type: 'error', label: '失败' },
}

const columns = [
  {
    title: '会议',
    key: 'title',
    render: (row: any) => row.title || row.id,
  },
  {
    title: '来源',
    key: 'source',
    width: 80,
    render: (row: any) =>
      row.source === 'live' ? h(NTag, { size: 'small', bordered: false }, '🎙 实时')
      : h(NTag, { size: 'small', bordered: false }, '📁 上传'),
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (row: any) => {
      const s = statusMap[row.status] || { type: 'default' as const, label: row.status }
      return h(NTag, { type: s.type, size: 'small' }, s.label)
    },
  },
  {
    title: '时长',
    key: 'duration_seconds',
    width: 80,
    render: (row: any) => {
      const m = Math.floor((row.duration_seconds || 0) / 60)
      const s = Math.floor((row.duration_seconds || 0) % 60)
      return `${m}:${s.toString().padStart(2, '0')}`
    },
  },
  {
    title: '句数',
    key: 'segment_count',
    width: 60,
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 140,
    render: (row: any) => {
      if (!row.created_at) return '-'
      const d = new Date(row.created_at)
      return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
    },
  },
  {
    title: '操作',
    key: 'action',
    width: 120,
    render: (row: any) => {
      return h(NSpace, { size: 'small' }, () => [
        h(NButton, { size: 'small', onClick: (e: Event) => { e.stopPropagation(); goToReport(row.id) } }, '查看'),
        h(
          NPopconfirm,
          { onPositiveClick: (e: Event) => { e.stopPropagation(); handleDelete(row.id) } },
          {
            trigger: () => h(NButton, { size: 'small', type: 'error', onClick: (e: Event) => e.stopPropagation() }, '删除'),
            default: () => '确定删除此会议？',
          }
        ),
      ])
    },
  },
]

onMounted(fetchMeetings)
</script>
```

- [ ] **Step 2: 编译验证**

```bash
cd python/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add python/frontend/src/views/HistoryView.vue python/static/
git commit -m "feat: migrate HistoryView from localStorage to server API"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 启动 Docker 服务（PostgreSQL + Redis）**

```bash
cd python && docker-compose up -d postgres redis
```

确认两个服务启动：

```bash
docker ps --filter "name=postgres" --filter "name=redis" --format "table {{.Names}}\t{{.Status}}"
```

- [ ] **Step 2: 启动 Python 后端**

```bash
cd python && python main.py
```

确认日志包含 `Database tables created/verified`。

- [ ] **Step 3: 运行 Demo 会议**

```bash
curl -X POST http://localhost:8000/api/v1/meeting/e2e-test/demo
```

Expected: 返回完整 report JSON，包含 transcript/summary/actions/insights。

- [ ] **Step 4: 验证持久化**

```bash
# 查询历史列表
curl http://localhost:8000/api/v1/meetings | python -m json.tool | head -20

# 查询会议详情
curl http://localhost:8000/api/v1/meeting/e2e-test | python -m json.tool | head -20
```

- [ ] **Step 5: 验证删除**

```bash
curl -X DELETE http://localhost:8000/api/v1/meeting/e2e-test
```

Expected: `{"status": "deleted", "meeting_id": "e2e-test"}`

- [ ] **Step 6: 用 DBeaver 连接 PostgreSQL 验证**

- Host: `localhost`, Port: `5432`
- Database: `meeting_assistant`
- User: `postgres`, Password: `password`
- 检查 `meetings`, `meeting_transcripts`, `meeting_summaries`, `meeting_action_items` 四张表数据

- [ ] **Step 7: Commit（最终）**

```bash
git add -A
git commit -m "feat: complete database persistence — PostgreSQL + Redis caching"
```
