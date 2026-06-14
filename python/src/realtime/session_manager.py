"""
LiveSessionManager — 实时会议会话管理器

协调 AudioBuffer → ChunkTranscriber → IncrementalAnalyzer 三组件流水线。
管理 WebSocket 连接和会话生命周期。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import WebSocket
from loguru import logger

from .audio_buffer import AudioBuffer
from .chunk_transcriber import ChunkTranscriber
from .incremental_analyzer import IncrementalAnalyzer
from ..integrations.llm_client import LLMClient
from ..models.schemas import (
    TranscriptResult,
    MeetingSummary,
    ActionResult,
    MeetingInsight,
)


class LiveSessionManager:
    """
    管理单次实时会议的生命周期。

    生命周期:
        WebSocket 连接 → start → 音频流 → stop → 最终分析 → 断开

    三个 asyncio.Task:
        1. audio_task:   WebSocket 接收音频 ⇒ AudioBuffer.feed()
        2. transcribe_task: AudioBuffer.process() ⇒ ChunkTranscriber ⇒ push
        3. analyze_timer_task:  定时检查 ⇒ IncrementalAnalyzer ⇒ push
    """

    def __init__(
        self,
        meeting_id: str,
        websocket: WebSocket,
        llm_client: LLMClient | None = None,
    ):
        self.meeting_id = meeting_id
        self.session_id = str(uuid.uuid4())[:8]
        self._ws = websocket
        self._llm = llm_client or LLMClient()

        self._buffer = AudioBuffer()
        self._transcriber: ChunkTranscriber | None = None
        self._analyzer: IncrementalAnalyzer | None = None

        self._running = False
        self._started_at: float = 0.0
        self._tasks: list[asyncio.Task] = []

        self.final_transcript: TranscriptResult | None = None
        self.final_summary: MeetingSummary | None = None
        self.final_actions: ActionResult | None = None
        self.final_insights: MeetingInsight | None = None

    async def run(self) -> None:
        """主入口 — 被 WebSocket 端点调用。"""
        await self._ws.send_json({
            "type": "connected",
            "meeting_id": self.meeting_id,
            "session_id": self.session_id,
        })
        logger.info(f"LiveSession started: {self.meeting_id}/{self.session_id}")

        started = await self._wait_for_start()
        if not started:
            return

        self._running = True
        self._started_at = time.time()

        self._transcriber = ChunkTranscriber(
            on_sentence=self._on_transcript_sentence
        )
        self._analyzer = IncrementalAnalyzer(
            llm_client=self._llm,
            on_summary=self._on_summary_update,
            on_actions=self._on_actions_update,
            on_insights=self._on_insights_update,
        )

        self._tasks = [
            asyncio.create_task(self._audio_loop()),
            asyncio.create_task(self._transcribe_loop()),
            asyncio.create_task(self._analyze_timer_loop()),
        ]

        await self._message_loop()

    async def _wait_for_start(self) -> bool:
        """等待 start 消息（超时 30 秒）。"""
        try:
            while True:
                raw = await asyncio.wait_for(self._ws.receive(), timeout=30.0)
                if "text" not in raw or not raw["text"]:
                    continue
                msg = json.loads(raw["text"])
                if msg.get("type") == "start":
                    logger.info(f"LiveSession received start: {self.meeting_id}")
                    return True
                elif msg.get("type") == "ping":
                    await self._ws.send_json({"type": "pong"})
        except asyncio.TimeoutError:
            await self._ws.send_json({
                "type": "error", "message": "Timeout waiting for start message",
            })
            return False
        except Exception as e:
            logger.error(f"LiveSession start error: {e}")
            return False

    async def _audio_loop(self) -> None:
        """后台任务：接收音频帧并喂入 buffer。"""
        logger.debug("audio_loop started")
        try:
            while self._running:
                raw = await asyncio.wait_for(self._ws.receive(), timeout=1.0)
                if "bytes" in raw and raw["bytes"]:
                    self._buffer.feed(raw["bytes"])
                elif "text" in raw and raw["text"]:
                    msg = json.loads(raw["text"])
                    if msg.get("type") == "ping":
                        await self._ws.send_json({"type": "pong"})
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            if self._running:
                logger.error(f"audio_loop error: {e}")
        logger.debug("audio_loop stopped")

    async def _transcribe_loop(self) -> None:
        """后台任务：持续从 buffer 取 chunk → 转写 → 推送。"""
        logger.debug("transcribe_loop started")
        try:
            while self._running:
                chunk = self._buffer.process()
                if chunk is not None and self._transcriber:
                    segments_before = self._transcriber.segment_count
                    await self._transcriber.transcribe_chunk(chunk)
                    segments_after = self._transcriber.segment_count

                    if self._analyzer and segments_after > segments_before:
                        new_count = segments_after - segments_before
                        new_texts = [
                            self._transcriber._accumulated_segments[i].text
                            for i in range(segments_before, segments_after)
                        ]
                        await self._analyzer.on_new_sentences(new_texts)
                else:
                    await asyncio.sleep(0.05)
        except Exception as e:
            if self._running:
                logger.error(f"transcribe_loop error: {e}")
        logger.debug("transcribe_loop stopped")

    async def _analyze_timer_loop(self) -> None:
        """后台任务：定时检查是否需要触发增量分析。"""
        logger.debug("analyze_timer_loop started")
        try:
            while self._running:
                await asyncio.sleep(10)
                if not self._analyzer or self._analyzer.pending_count <= 0:
                    continue
                ref_time = (
                    self._analyzer._last_analysis_time
                    if self._analyzer._last_analysis_time > 0
                    else self._started_at
                )
                elapsed = time.time() - ref_time
                if elapsed >= IncrementalAnalyzer.TRIGGER_TIME_SECONDS:
                    await self._analyzer.force_analyze()
        except Exception as e:
            if self._running:
                logger.error(f"analyze_timer_loop error: {e}")
        logger.debug("analyze_timer_loop stopped")

    async def _message_loop(self) -> None:
        """主消息循环：处理 stop。"""
        try:
            while self._running:
                raw = await asyncio.wait_for(self._ws.receive(), timeout=1.0)
                if "text" in raw and raw["text"]:
                    msg = json.loads(raw["text"])
                    if msg.get("type") == "stop":
                        logger.info(f"LiveSession received stop: {self.meeting_id}")
                        await self._handle_stop()
                        break
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"message_loop error: {e}")
            await self._handle_stop()

    async def _handle_stop(self) -> None:
        """停止会话：flush → 最终分析 → 发送 completed。"""
        self._running = False

        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

        # Flush 剩余音频
        remaining = self._buffer.flush()
        if remaining and self._transcriber:
            await self._transcriber.transcribe_chunk(remaining)

        # 最终分析
        if self._transcriber and self._analyzer and self._transcriber.accumulated_text:
            await self._analyzer.force_analyze()

        if self._transcriber:
            self.final_transcript = self._transcriber.build_transcript_result(
                self.meeting_id
            )

        elapsed = time.time() - self._started_at if self._started_at else 0
        await self._ws.send_json({
            "type": "completed",
            "meeting_id": self.meeting_id,
            "session_id": self.session_id,
            "duration_seconds": round(elapsed, 1),
            "segment_count": (
                self._transcriber.segment_count if self._transcriber else 0
            ),
            "status": "completed",
        })
        logger.info(
            f"LiveSession completed: {self.meeting_id}/{self.session_id} "
            f"({elapsed:.1f}s)"
        )

    # ---- WebSocket 推送回调 ----

    async def _on_transcript_sentence(self, segment) -> None:
        try:
            await self._ws.send_json({
                "type": "transcript_delta",
                "data": segment.model_dump(),
            })
        except Exception as e:
            logger.error(f"Failed to send transcript_delta: {e}")

    async def _on_summary_update(self, summary: MeetingSummary) -> None:
        self.final_summary = summary
        try:
            await self._ws.send_json({
                "type": "summary_update",
                "data": summary.model_dump(),
            })
        except Exception as e:
            logger.error(f"Failed to send summary_update: {e}")

    async def _on_actions_update(self, actions: ActionResult) -> None:
        self.final_actions = actions
        try:
            await self._ws.send_json({
                "type": "actions_update",
                "data": actions.model_dump(),
            })
        except Exception as e:
            logger.error(f"Failed to send actions_update: {e}")

    async def _on_insights_update(self, insights: MeetingInsight) -> None:
        self.final_insights = insights
        try:
            await self._ws.send_json({
                "type": "insights_update",
                "data": insights.model_dump(),
            })
        except Exception as e:
            logger.error(f"Failed to send insights_update: {e}")
