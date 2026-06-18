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
            if isinstance(cached, str):
                data = json.loads(cached)
            else:
                data = cached
            return (
                [Meeting.model_validate(m) for m in data["items"]],
                data["total"],
            )

        count_result = await self._db.execute(
            select(func.count()).select_from(Meeting)
        )
        total = count_result.scalar_one()

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
        await self._cache_set(
            cache_key, json.dumps(payload, default=str), ttl=TTL_LIST
        )
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
        await self._cache_delete(f"meeting:{meeting_id}")
        await self._cache_set(f"meeting:{meeting_id}", meeting.model_dump())
        await self._invalidate_list_cache()
        return meeting

    async def delete_meeting(self, meeting_id: str) -> bool:
        """删除会议及所有关联数据。"""
        for model in [MeetingActionItemModel, MeetingSummaryModel, MeetingTranscript]:
            await self._db.execute(
                sa_delete(model).where(model.meeting_id == meeting_id)
            )
        result = await self._db.execute(
            sa_delete(Meeting).where(Meeting.id == meeting_id)
        )
        await self._db.flush()
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
        await self._db.execute(
            sa_delete(MeetingTranscript).where(
                MeetingTranscript.meeting_id == meeting_id
            )
        )
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
            if isinstance(cached, str):
                data = json.loads(cached)
            else:
                data = cached
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

    async def save_summary(
        self, meeting_id: str, summary: dict
    ) -> MeetingSummaryModel:
        """保存/覆盖会议纪要。"""
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

    async def get_action_items(
        self, meeting_id: str
    ) -> list[MeetingActionItemModel]:
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

    async def _cache_set(
        self, key: str, value, ttl: int = TTL_MEETING
    ) -> None:
        if not self._cache:
            return
        try:
            payload = (
                json.dumps(value, default=str)
                if not isinstance(value, str)
                else value
            )
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
            keys = [f"meeting:list:page:{p}" for p in range(1, 11)]
            for k in keys:
                await self._cache.delete(k)
        except Exception:
            pass
