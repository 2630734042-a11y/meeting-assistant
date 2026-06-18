# 数据库持久化设计规格

> **日期**: 2026-06-16
> **决策**: 方案B（PostgreSQL全量 + Redis缓存）、ORM: SQLModel、Redis: 纯缓存

---

## 1. 目标

将项目从「内存存储 + localStorage」升级为 PostgreSQL + Redis 双层持久化：
- 会议历史支持跨设备、跨会话查询
- 服务重启数据不丢失
- 高频查询走缓存，减少数据库压力

---

## 2. 架构

```
FastAPI Server
├── REST routes
│   ├── GET  /api/v1/meetings          (新增)
│   ├── DELETE /api/v1/meeting/{id}    (新增)
│   ├── GET  /api/v1/meeting/{id}      (新增)
│   └── 现有端点 → 内部改为写DB
├── 中间件层
│   └── Redis 缓存 (TTL: 120s-300s)
├── 数据访问层 (src/db/)
│   ├── models.py      — 4张SQLModel表
│   └── repository.py  — CRUD封装
├── PostgreSQL 16 (主存储)
└── Redis 7 (纯缓存，不持久化)
```

### 数据流

```
写: API → Repository → PostgreSQL → 删Redis cache key
读: API → Redis (miss) → Repository → PostgreSQL → 回写Redis → 返回
读: API → Redis (hit)  → 直接返回
```

---

## 3. 数据模型 (SQLModel)

新建 `python/src/db/models.py`，与现有 `schemas.py` (Pydantic) 共存：

```python
# === Meeting（会议主表）===
class Meeting(SQLModel, table=True):
    __tablename__ = "meetings"
    id: str = Field(primary_key=True)          # meeting_id
    title: str | None = None
    status: str = "created"                    # MeetingStatus
    source: str = "live"                       # "live" | "upload"
    duration_seconds: float = 0.0
    segment_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# === MeetingTranscript（转写段，1:N）===
class MeetingTranscript(SQLModel, table=True):
    __tablename__ = "meeting_transcripts"
    id: int | None = Field(default=None, primary_key=True)
    meeting_id: str = Field(foreign_key="meetings.id", index=True)
    seq: int                                   # 顺序号
    speaker: str
    text: str
    start: float                               # 绝对秒
    end: float
    confidence: float = 0.0

# === MeetingSummary（纪要，1:1）===
class MeetingSummary(SQLModel, table=True):
    __tablename__ = "meeting_summaries"
    id: int | None = Field(default=None, primary_key=True)
    meeting_id: str = Field(foreign_key="meetings.id", unique=True)
    title: str = ""
    topics: str = ""                            # JSON string of TopicSummary[]
    decisions: str = ""
    conclusions: str = ""

# === MeetingActionItem（待办，1:N）===
class MeetingActionItem(SQLModel, table=True):
    __tablename__ = "meeting_action_items"
    id: int | None = Field(default=None, primary_key=True)
    meeting_id: str = Field(foreign_key="meetings.id", index=True)
    task: str
    owner: str
    priority: str = "medium"                    # low/medium/high/urgent
    due_date: str | None = None
    review_status: str = "pending"              # pending/approved/rejected
    jira_key: str | None = None
    feishu_task_id: str | None = None
```

### 与现有 schemas.py 的关系

现有 Pydantic 模型（`TranscriptResult`, `MeetingSummary`, `ActionResult`, `ActionItem` 等）**不动**，继续用于：
- API 请求/响应序列化
- Agent 间通信
- LangGraph State 定义

SQLModel 表模型和 Pydantic 模型通过 `.model_dump()` / `model_validate()` 互转。转换逻辑集中在 `repository.py`。

---

## 4. Redis 缓存策略

| Key Pattern | TTL | 内容 |
|---|---|---|
| `meeting:{id}` | 300s | Meeting 详情 JSON |
| `meeting:{id}:transcript` | 300s | 转写段列表 JSON |
| `meeting:list:page:{n}` | 120s | 历史列表第 n 页 JSON |

### 缓存逻辑

- **读**: 先查 Redis → hit 返回 → miss 查 PostgreSQL → 回写 Redis
- **写**: 创建/更新 Meeting 时删除对应 `meeting:{id}*` 的所有 key
- **列表**: 任何新 Meeting 创建/删除时，删除所有 `meeting:list:*` key
- Redis 不可用时回退到 PostgreSQL 直查（不报错）

---

## 5. 数据访问层

新建 `python/src/db/` 目录：

```
src/db/
├── __init__.py       # get_db, get_cache, create_db_and_tables
├── models.py         # 4 张 SQLModel 表定义
└── repository.py     # MeetingRepository 类
```

### 5.1 `__init__.py` — 依赖注入

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

engine = create_async_engine(DATABASE_URL, echo=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session

async def get_cache() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)

async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
```

### 5.2 `repository.py` — MeetingRepository

```python
class MeetingRepository:
    def __init__(self, db: AsyncSession, cache: Redis | None = None):
        ...
    
    # 会议 CRUD
    async def create_meeting(self, meeting: Meeting) -> Meeting: ...
    async def get_meeting(self, meeting_id: str) -> Meeting | None: ...
    async def list_meetings(self, page: int = 1, size: int = 20) -> tuple[list[Meeting], int]: ...
    async def update_meeting(self, meeting_id: str, **kwargs) -> Meeting: ...
    async def delete_meeting(self, meeting_id: str) -> bool: ...
    
    # 转写
    async def save_transcript(self, meeting_id: str, segments: list[dict]) -> list[MeetingTranscript]: ...
    async def get_transcript(self, meeting_id: str) -> list[MeetingTranscript]: ...
    
    # 纪要
    async def save_summary(self, meeting_id: str, summary: dict) -> MeetingSummary: ...
    async def get_summary(self, meeting_id: str) -> MeetingSummary | None: ...
    
    # 待办
    async def save_action_items(self, meeting_id: str, items: list[dict]) -> list[MeetingActionItem]: ...
    async def get_action_items(self, meeting_id: str) -> list[MeetingActionItem]: ...
    async def update_action_review(self, item_id: int, status: str) -> MeetingActionItem: ...
```

---

## 6. API 改动

### 新增端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/meetings` | 历史列表，query: `?page=1&size=20` |
| `GET` | `/api/v1/meeting/{id}` | 会议详情（含转写/纪要/待办） |
| `DELETE` | `/api/v1/meeting/{id}` | 删除会议及关联数据 |

### 改造现有端点

| 端点 | 改动 |
|------|------|
| 文件上传完成 | `meeting_results[id] = result` → 写入 PostgreSQL |
| 实时会议完成 | `_handle_stop()` 后写入 PostgreSQL |
| Demo 会议 | `meeting_results[id] = result` → 写入 PostgreSQL |
| `/meeting/{id}/status` | `meeting_results.get(id)` → `repo.get_meeting(id)` |
| `/meeting/{id}/review` | 更新内存 → `repo.update_action_review()` |

### 启动初始化

```python
@app.on_event("startup")
async def startup():
    await create_db_and_tables()
```

---

## 7. 前端改动

| 文件 | 改动 |
|------|------|
| `HistoryView.vue` | 从 `localStorage` 读取 → 调用 `GET /api/v1/meetings` |
| `composables/useLiveSession.ts` | 不需要改（transcript_delta 推送逻辑不变） |
| `api.ts` 或等同文件 | 新增 `fetchMeetings()`, `fetchMeeting(id)`, `deleteMeeting(id)` |

### HistoryView 改动要点

- 页面加载时调用 `GET /api/v1/meetings?page=1`
- 移除 `localStorage` 读写逻辑
- 加简单的分页控件
- 删除按钮调用 `DELETE /api/v1/meeting/{id}`

---

## 8. 配置

在 `.env.example` 和 `.env` 中新增：

```bash
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/meeting_assistant
REDIS_URL=redis://localhost:6379/0
```

`docker-compose.yml` 已有 PostgreSQL 和 Redis 服务定义，无需改动。

---

## 9. 依赖

`pyproject.toml` 新增依赖：

```toml
"sqlmodel>=0.0.22",
"asyncpg>=0.30.0",
"redis>=5.2.0",
```

已有 `sqlalchemy>=2.0.0`（SQLModel 依赖它），无需重复。

---

## 10. 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| **新建** | `python/src/db/__init__.py` | 引擎、依赖注入、建表 |
| **新建** | `python/src/db/models.py` | 4张SQLModel表 |
| **新建** | `python/src/db/repository.py` | CRUD + 缓存逻辑 |
| **修改** | `python/src/websocket/server.py` | 现有端点改DB、新增3个REST端点 |
| **修改** | `python/frontend/src/views/HistoryView.vue` | localStorage → API |
| **修改** | `python/frontend/src/shared/api.ts` | 新增 API 函数 |
| **修改** | `python/pyproject.toml` | 新增依赖 |
| **修改** | `.env.example` | DATABASE_URL + REDIS_URL |

---

## 11. 验收标准

1. `docker-compose up -d` 后访问 `http://localhost:8000/docs` 可看到新增的 3 个端点
2. 文件上传会议 → 数据写入 PostgreSQL → 重启服务 → 历史记录仍可查询
3. 实时会议结束 → 数据写入 PostgreSQL → 历史记录可见
4. 同一会议第二次查询命中 Redis 缓存，响应时间 < 50ms
5. 删除会议 → PostgreSQL 删除 → 历史列表不再显示
6. 现有所有功能不受影响（文件上传、实时会议、Demo模式、HITL审核）
