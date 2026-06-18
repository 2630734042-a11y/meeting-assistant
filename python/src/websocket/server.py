"""
WebSocket 服务器 - 实时音频流接入和结果推送

支持两种模式:
1. 实时模式: 客户端通过 WebSocket 发送音频流，服务端实时返回转写结果
2. 文件模式: 通过 REST API 上传音频文件，异步处理后推送结果
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv()

from ..graph.meeting_graph import run_meeting_pipeline, resume_meeting_pipeline, compile_meeting_graph
from ..models.schemas import MeetingStatus, Priority
from ..realtime.session_manager import LiveSessionManager
from ..db import get_db, get_cache, create_db_and_tables, new_db_session
from ..db.repository import MeetingRepository

from ..utils.media_utils import (
    SUPPORTED_VIDEO_EXTENSIONS,
    is_video_file,
    save_upload_streaming,
    extract_audio_from_video,
)


app = FastAPI(
    title="多Agent智能会议助手",
    description="企业级5-Agent会议全流程自动化系统",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await create_db_and_tables()
    logger.info("Database tables created/verified")


# 存储活跃的 WebSocket 连接和会议状态
active_connections: dict[str, WebSocket] = {}
meeting_results: dict[str, dict] = {}  # 保留用于 LangGraph checkpoint 状态


async def _save_meeting_to_db(
    meeting_id: str,
    result: dict,
    title: str | None = None,
    source: str = "upload",
) -> None:
    """将 Pipeline 结果写入 PostgreSQL。"""
    try:
        async with new_db_session() as db:
            repo = MeetingRepository(db)
            await repo.create_meeting(
                meeting_id,
                title=title or f"会议 {meeting_id}",
                source=source,
                status="completed",
            )

            transcript = result.get("transcript")
            if transcript:
                segs = (
                    transcript.model_dump().get("segments", [])
                    if hasattr(transcript, "model_dump")
                    else transcript.get("segments", [])
                )
                if segs:
                    await repo.save_transcript(meeting_id, segs)

            summary = result.get("summary")
            if summary:
                sd = summary.model_dump() if hasattr(summary, "model_dump") else summary
                if sd:
                    await repo.save_summary(meeting_id, sd)

            actions = result.get("actions")
            if actions:
                ad = actions.model_dump() if hasattr(actions, "model_dump") else actions
                items = ad.get("action_items", []) if isinstance(ad, dict) else []
                if items:
                    await repo.save_action_items(meeting_id, items)

            duration = result.get(
                "duration_seconds",
                transcript.model_dump().get("duration_seconds", 0)
                if transcript and hasattr(transcript, "model_dump")
                else 0,
            )
            await repo.update_meeting(
                meeting_id,
                duration_seconds=duration,
                segment_count=len(
                    transcript.model_dump().get("segments", [])
                    if transcript and hasattr(transcript, "model_dump")
                    else []
                ),
            )
    except Exception as e:
        logger.error(f"Failed to save meeting {meeting_id} to DB: {e}")


# ============================================================
# WebSocket 端点
# ============================================================

@app.websocket("/ws/meeting/{meeting_id}")
async def websocket_meeting(websocket: WebSocket, meeting_id: str):
    """
    WebSocket 会议端点

    协议:
    - 客户端发送: 音频二进制帧 / JSON控制消息
    - 服务端返回: JSON格式的处理结果

    控制消息:
    - {"type": "start"}: 开始录制
    - {"type": "stop"}: 停止录制，触发Pipeline处理
    - {"type": "ping"}: 心跳
    """
    await websocket.accept()
    active_connections[meeting_id] = websocket
    audio_buffer = bytearray()

    logger.info(f"WebSocket connected: {meeting_id}")

    try:
        await websocket.send_json({
            "type": "connected",
            "meeting_id": meeting_id,
            "message": "会议助手已连接，发送音频数据开始录制",
        })

        while True:
            data = await websocket.receive()

            if "bytes" in data and data["bytes"]:
                audio_buffer.extend(data["bytes"])
                await websocket.send_json({
                    "type": "recording",
                    "buffer_size": len(audio_buffer),
                })

            elif "text" in data and data["text"]:
                message = json.loads(data["text"])
                msg_type = message.get("type", "")

                if msg_type == "stop":
                    await websocket.send_json({
                        "type": "processing",
                        "message": "正在处理音频，请稍候...",
                    })

                    result = await run_meeting_pipeline(
                        meeting_id=meeting_id,
                        audio_data=bytes(audio_buffer),
                    )
                    meeting_results[meeting_id] = result
                    await _save_meeting_to_db(meeting_id, result, source="upload")

                    await _send_results(websocket, result)
                    audio_buffer.clear()

                elif msg_type == "demo":
                    await websocket.send_json({
                        "type": "processing",
                        "message": "运行演示模式...",
                    })
                    result = await run_meeting_pipeline(
                        meeting_id=meeting_id,
                        audio_data=b"",
                    )
                    meeting_results[meeting_id] = result
                    await _save_meeting_to_db(meeting_id, result, source="upload")

                    await _send_results(websocket, result)

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {meeting_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {meeting_id} - {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass
    finally:
        active_connections.pop(meeting_id, None)


# ============================================================
# 实时会议 WebSocket 端点 (NEW)
# ============================================================

@app.websocket("/ws/live/{meeting_id}")
async def websocket_live_meeting(websocket: WebSocket, meeting_id: str):
    """
    实时会议 WebSocket 端点 — Level 2 Streaming

    协议:
    - 客户端发送:
        - 二进制 PCM 16kHz 16bit mono 音频帧
        - {"type": "start", "meeting_id": "...", "title": "..."}
        - {"type": "stop"}
        - {"type": "ping"}

    - 服务端返回:
        - {"type": "connected", "meeting_id": "...", "session_id": "..."}
        - {"type": "transcript_delta", "data": TranscriptSegment}
        - {"type": "summary_update", "data": MeetingSummary}
        - {"type": "actions_update", "data": ActionResult}
        - {"type": "insights_update", "data": MeetingInsight}
        - {"type": "completed", "meeting_id": "...", ...}
        - {"type": "error", "message": "..."}
        - {"type": "pong"}
    """
    await websocket.accept()

    session = LiveSessionManager(
        meeting_id=meeting_id,
        websocket=websocket,
    )

    try:
        await session.run()
        # 会议结束后写入 DB
        await _save_live_session_to_db(meeting_id, session)
    except Exception as e:
        logger.error(f"Live session error: {meeting_id} - {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass


async def _save_live_session_to_db(meeting_id: str, session: LiveSessionManager) -> None:
    """将实时会议结果写入 PostgreSQL。"""
    try:
        async with new_db_session() as db:
            repo = MeetingRepository(db)
            await repo.create_meeting(
                meeting_id,
                title=f"实时会议 {meeting_id}",
                source="live",
                status="completed",
            )
            if session.final_transcript:
                segs = session.final_transcript.model_dump().get("segments", [])
                if segs:
                    await repo.save_transcript(meeting_id, segs)
                    await repo.update_meeting(
                        meeting_id,
                        duration_seconds=session.final_transcript.duration_seconds,
                        segment_count=len(segs),
                    )
    except Exception as e:
        logger.error(f"Failed to save live session {meeting_id} to DB: {e}")


async def _send_results(websocket: WebSocket, state: dict):
    """将 Pipeline 处理结果分步推送给客户端"""
    # 转写结果
    transcript = state.get("transcript")
    if transcript:
        await websocket.send_json({
            "type": "transcript",
            "data": transcript.model_dump() if hasattr(transcript, "model_dump") else {},
        })

    # 摘要结果
    summary = state.get("summary")
    if summary:
        await websocket.send_json({
            "type": "summary",
            "data": summary.model_dump() if hasattr(summary, "model_dump") else {},
        })

    # 待办结果
    actions = state.get("actions")
    if actions:
        await websocket.send_json({
            "type": "actions",
            "data": actions.model_dump() if hasattr(actions, "model_dump") else {},
        })

    # 洞察结果
    insights = state.get("insights")
    if insights:
        await websocket.send_json({
            "type": "insights",
            "data": insights.model_dump() if hasattr(insights, "model_dump") else {},
        })

    # 跟进结果
    followup = state.get("followup")
    if followup:
        await websocket.send_json({
            "type": "followup",
            "data": followup.model_dump() if hasattr(followup, "model_dump") else {},
        })

    # 完成通知
    errors = state.get("errors", [])
    await websocket.send_json({
        "type": "completed",
        "meeting_id": state.get("meeting_id"),
        "status": state.get("status", MeetingStatus.COMPLETED),
        "errors": errors,
    })


# ============================================================
# REST API 端点
# ============================================================

@app.get("/")
async def root():
    return {
        "name": "多Agent智能会议助手",
        "version": "1.0.0",
        "docs": "/docs",
        "websocket": "ws://localhost:8000/ws/meeting/{meeting_id}",
    }


@app.post("/api/v1/meeting/start")
async def start_meeting():
    """创建新会议"""
    meeting_id = str(uuid.uuid4())[:12]
    return {
        "meeting_id": meeting_id,
        "websocket_url": f"ws://localhost:8000/ws/meeting/{meeting_id}",
        "status": "created",
    }


@app.post("/api/v1/meeting/{meeting_id}/upload")
async def upload_audio(
    meeting_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
):
    """上传音频文件并处理"""
    audio_data = await file.read()
    logger.info(
        f"Received audio upload: {meeting_id}, size={len(audio_data)} bytes"
    )

    thread_id = f"thread-{meeting_id}"
    result = await run_meeting_pipeline(
        meeting_id=meeting_id,
        audio_data=audio_data,
        thread_id=thread_id,
    )
    meeting_results[meeting_id] = result

    # 写入数据库
    await _save_meeting_to_db(meeting_id, result, title=file.filename, source="upload")

    return {
        "meeting_id": meeting_id,
        "thread_id": thread_id,
        "status": result.get("status", "completed"),
        "errors": result.get("errors", []),
    }


@app.post("/api/v1/meeting/{meeting_id}/upload-video")
async def upload_video(
    meeting_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
):
    """
    上传视频文件并处理

    支持格式: MP4, MKV, WebM, AVI, MOV, FLV, WMV
    自动提取音频后走完整 5-Agent Pipeline
    """
    # 1. 校验文件格式
    if not file.filename or not is_video_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的视频格式，支持的格式: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))}",
        )

    # 2. 校验文件非空
    if not file.size:
        raise HTTPException(status_code=400, detail="上传文件为空")

    logger.info(
        f"Received video upload: {meeting_id}, "
        f"file={file.filename}, size={file.size} bytes"
    )

    # 3. 流式写入临时文件
    suffix = Path(file.filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    audio_bytes = None
    try:
        # 分块写入磁盘
        await save_upload_streaming(file, tmp_path)
        file_size_on_disk = tmp_path.stat().st_size
        logger.debug(f"Video saved: {tmp_path} ({file_size_on_disk} bytes)")

        # 4. FFmpeg 提取音频
        audio_bytes = await extract_audio_from_video(tmp_path)
        logger.info(f"Audio extracted: {len(audio_bytes)} bytes")

    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f"服务器未安装 FFmpeg: {e}",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        )
    finally:
        # 5. 清理临时视频文件
        try:
            tmp_path.unlink()
            logger.debug(f"Cleaned up temp file: {tmp_path}")
        except FileNotFoundError:
            pass

    # 6. 走现有 Pipeline
    thread_id = f"thread-{meeting_id}"
    result = await run_meeting_pipeline(
        meeting_id=meeting_id,
        audio_data=audio_bytes,
        thread_id=thread_id,
    )
    meeting_results[meeting_id] = result

    # 写入数据库
    await _save_meeting_to_db(meeting_id, result, title=file.filename, source="upload")

    return {
        "meeting_id": meeting_id,
        "thread_id": thread_id,
        "video_filename": file.filename,
        "video_size": file.size,
        "audio_size": len(audio_bytes),
        "status": result.get("status", "completed"),
        "errors": result.get("errors", []),
    }


@app.put("/api/v1/meeting/{meeting_id}/actions/review")
async def review_actions(meeting_id: str, request: Request):
    """
    提交待办审核结果（HITL 介入点）

    接收前端逐条编辑/确认/删除后的最终待办列表。
    """
    result = meeting_results.get(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail="Meeting not found")

    body = await request.json()
    reviewed_items = body.get("items", [])

    # result["actions"] 可能是 ActionResult 对象或 dict
    actions = result.get("actions")
    if not actions:
        raise HTTPException(status_code=404, detail="No action items found")

    # ActionResult 是 pydantic BaseModel，.action_items 是 list[ActionItem]
    action_items = actions.action_items if hasattr(actions, 'action_items') else actions.get("action_items", [])

    updated_count = 0
    for review in reviewed_items:
        idx = review.get("index", -1)
        if 0 <= idx < len(action_items):
            item = action_items[idx]
            item.review_status = review.get("review_status", item.review_status)

            if item.review_status in ("confirmed", "modified"):
                item.assignee = review.get("assignee", item.assignee)
                item.task = review.get("task", item.task)
                item.deadline = review.get("deadline", item.deadline)
                if "priority" in review:
                    try:
                        item.priority = Priority(review["priority"])
                    except ValueError:
                        pass
            updated_count += 1

    logger.info(
        f"Review submitted for {meeting_id}: {updated_count} items"
    )

    # 同步更新数据库中的待办审核状态
    try:
        async with new_db_session() as db:
            repo = MeetingRepository(db)
            for review in reviewed_items:
                item_id = review.get("id")
                if item_id is not None:
                    await repo.update_action_review(
                        item_id,
                        review.get("review_status", "reviewed"),
                    )
    except Exception as e:
        logger.warning(f"Failed to sync review to DB (non-fatal): {e}")

    # 将更新后的 actions 写回 LangGraph checkpoint，确保 resume 读到审核结果
    thread_id = body.get("thread_id", f"thread-{meeting_id}")
    try:
        compiled_graph = compile_meeting_graph()
        config = {"configurable": {"thread_id": thread_id}}
        await compiled_graph.aupdate_state(
            config,
            {"actions": actions},
        )
        logger.debug(f"Checkpoint updated for thread={thread_id}")
    except Exception as e:
        logger.warning(f"Failed to update checkpoint (non-fatal): {e}")

    return {
        "meeting_id": meeting_id,
        "reviewed_count": updated_count,
        "status": "reviewed",
    }


@app.post("/api/v1/meeting/{meeting_id}/demo")
async def run_demo(
    meeting_id: str = "demo",
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
):
    """运行演示模式（无需音频）"""
    thread_id = f"thread-{meeting_id}"
    result = await run_meeting_pipeline(
        meeting_id=meeting_id,
        audio_data=b"",
        thread_id=thread_id,
    )
    meeting_results[meeting_id] = result
    await _save_meeting_to_db(meeting_id, result, title=f"Demo {meeting_id}", source="upload")

    response: dict[str, Any] = {
        "meeting_id": meeting_id,
        "thread_id": thread_id,
        "status": result.get("status"),
    }

    for key in ("transcript", "summary", "actions", "insights", "followup"):
        val = result.get(key)
        if val and hasattr(val, "model_dump"):
            response[key] = val.model_dump()

    response["errors"] = result.get("errors", [])
    return response


@app.post("/api/v1/meeting/{meeting_id}/resume")
async def resume_pipeline(meeting_id: str, request: Request):
    """
    确认审核完毕，继续执行 sync_actions + FollowUp
    """
    body = await request.json()
    thread_id = body.get("thread_id", f"thread-{meeting_id}")

    logger.info(f"Resuming pipeline: {meeting_id} (thread={thread_id})")

    try:
        final_state = await resume_meeting_pipeline(thread_id=thread_id)
        meeting_results[meeting_id] = final_state

        # 写回数据库（更新 actions 审核状态）
        await _save_meeting_to_db(meeting_id, final_state, source="upload")

        return {
            "meeting_id": meeting_id,
            "status": final_state.get("status", "syncing"),
            "message": "Pipeline resumed, sync in progress",
        }
    except Exception as e:
        logger.error(f"Resume failed: {e}")
        raise HTTPException(status_code=500, detail=f"恢复执行失败: {e}")


@app.get("/api/v1/meeting/{meeting_id}/transcript")
async def get_transcript(meeting_id: str):
    """获取转写结果"""
    # 优先查 DB
    try:
        async with new_db_session() as db:
            repo = MeetingRepository(db)
            rows = await repo.get_transcript(meeting_id)
            if rows:
                return {
                    "segments": [
                        {
                            "speaker": r.speaker,
                            "text": r.text,
                            "start": r.start,
                            "end": r.end,
                            "confidence": r.confidence,
                        }
                        for r in rows
                    ]
                }
    except Exception:
        pass

    # fallback 到内存
    result = meeting_results.get(meeting_id)
    if not result:
        return {"error": "Meeting not found"}
    transcript = result.get("transcript")
    if transcript and hasattr(transcript, "model_dump"):
        return transcript.model_dump()
    return {"error": "Transcript not available"}


@app.get("/api/v1/meeting/{meeting_id}/summary")
async def get_summary(meeting_id: str):
    """获取会议纪要"""
    try:
        async with new_db_session() as db:
            repo = MeetingRepository(db)
            row = await repo.get_summary(meeting_id)
            if row:
                return {
                    "title": row.title,
                    "topics": json.loads(row.topics) if row.topics else [],
                    "decisions": row.decisions,
                    "conclusions": row.conclusions,
                }
    except Exception:
        pass

    result = meeting_results.get(meeting_id)
    if not result:
        return {"error": "Meeting not found"}
    summary = result.get("summary")
    if summary and hasattr(summary, "model_dump"):
        return summary.model_dump()
    return {"error": "Summary not available"}


@app.get("/api/v1/meeting/{meeting_id}/actions")
async def get_actions(meeting_id: str):
    """获取待办事项"""
    try:
        async with new_db_session() as db:
            repo = MeetingRepository(db)
            rows = await repo.get_action_items(meeting_id)
            if rows:
                return {
                    "action_items": [
                        {
                            "id": r.id,
                            "task": r.task,
                            "owner": r.owner,
                            "priority": r.priority,
                            "due_date": r.due_date,
                            "review_status": r.review_status,
                            "jira_key": r.jira_key,
                            "feishu_task_id": r.feishu_task_id,
                        }
                        for r in rows
                    ]
                }
    except Exception:
        pass

    result = meeting_results.get(meeting_id)
    if not result:
        return {"error": "Meeting not found"}
    actions = result.get("actions")
    if actions and hasattr(actions, "model_dump"):
        return actions.model_dump()
    return {"error": "Actions not available"}


@app.get("/api/v1/meeting/{meeting_id}/insights")
async def get_insights(meeting_id: str):
    """获取会议洞察"""
    result = meeting_results.get(meeting_id)
    if not result:
        return {"error": "Meeting not found"}
    insights = result.get("insights")
    if insights and hasattr(insights, "model_dump"):
        return insights.model_dump()
    return {"error": "Insights not available"}


@app.get("/api/v1/meeting/{meeting_id}/report")
async def get_full_report(meeting_id: str):
    """获取完整报告"""
    # 优先从 DB 组装
    try:
        async with new_db_session() as db:
            repo = MeetingRepository(db)
            meeting = await repo.get_meeting(meeting_id)
            if meeting:
                transcript_rows = await repo.get_transcript(meeting_id)
                summary_row = await repo.get_summary(meeting_id)
                action_rows = await repo.get_action_items(meeting_id)

                response: dict[str, Any] = {"meeting_id": meeting_id}
                if transcript_rows:
                    response["transcript"] = {
                        "segments": [
                            {"speaker": r.speaker, "text": r.text, "start": r.start, "end": r.end, "confidence": r.confidence}
                            for r in transcript_rows
                        ]
                    }
                if summary_row:
                    response["summary"] = {
                        "title": summary_row.title,
                        "topics": json.loads(summary_row.topics) if summary_row.topics else [],
                        "decisions": summary_row.decisions,
                        "conclusions": summary_row.conclusions,
                    }
                if action_rows:
                    response["actions"] = {
                        "action_items": [r.model_dump() for r in action_rows]
                    }
                if response:
                    response["status"] = meeting.status
                    return response
    except Exception:
        pass

    # fallback 到内存
    result = meeting_results.get(meeting_id)
    if not result:
        return {"error": "Meeting not found"}

    response = {"meeting_id": meeting_id}
    for key in ("transcript", "summary", "actions", "insights", "followup"):
        val = result.get(key)
        if val and hasattr(val, "model_dump"):
            response[key] = val.model_dump()

    response["errors"] = result.get("errors", [])
    return response


# ============================================================
# 新增: 历史记录 API（DB 持久化）
# ============================================================

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


# ============================================================
# 静态文件服务 (SPA)
# ============================================================

from fastapi.staticfiles import StaticFiles

_static_path = Path(__file__).resolve().parent.parent.parent / "static"
if _static_path.exists() and (_static_path / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_static_path), html=True), name="static")
    logger.info(f"Static files mounted from: {_static_path}")
