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
# MeetingSummaryModel — 会议纪要 (1:1)
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
# MeetingActionItemModel — 待办事项 (1:N)
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
