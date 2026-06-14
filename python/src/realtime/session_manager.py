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

    并发模型:
        1. _receive_loop (主协程):  统一接收 WebSocket 消息，路由 binary→buffer / stop→结束
        2. transcribe_task (后台):  AudioBuffer.process() ⇒ ChunkTranscriber ⇒ push
        3. analyze_timer_task (后台): 定时检查 ⇒ IncrementalAnalyzer ⇒ push
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

        self._buffer = AudioBuffer(
            silence_threshold_ms=800,
            max_chunk_ms=5000,      # 5秒强制切分，更快出第一块
            min_speech_ms=500,      # 0.5秒语音即可，减少丢弃短句
        )
        self._transcriber: ChunkTranscriber | None = None
        self._analyzer: IncrementalAnalyzer | None = None

        self._running = False
        self._started_at: float = 0.0
        self._tasks: list[asyncio.Task] = []

        # 首次成功标记（全链路诊断用）
        self._first_feed = True
        self._first_chunk = True
        self._first_transcribe_call = True
        self._first_push = True
        self._first_analyzer_feed = True
        self._first_force_analyze = True

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
            asyncio.create_task(self._transcribe_loop()),
            asyncio.create_task(self._analyze_timer_loop()),
        ]

        await self._receive_loop()

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

    async def _receive_loop(self) -> None:
        """
        统一的消息接收循环（解决 _audio_loop / _message_loop 并发 receive() 竞态）。
        路由：binary → buffer.feed() / text:stop → _handle_stop() / text:ping → pong
        """
        logger.debug("receive_loop started")
        _binary_count = 0
        _binary_bytes = 0
        try:
            while self._running:
                try:
                    raw = await asyncio.wait_for(self._ws.receive(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue  # 1秒无数据，正常轮询，继续等待

                if "bytes" in raw and raw["bytes"]:
                    data = raw["bytes"]
                    self._buffer.feed(data)
                    if self._first_feed:
                        logger.info(
                            f"[⑥ buffer.feed] 首次收到音频数据 | "
                            f"bytes={len(data)}, "
                            f"buffer_size={len(self._buffer._buffer)} bytes"
                        )
                        self._first_feed = False
                    _binary_count += 1
                    _binary_bytes += len(data)
                    if _binary_count % 100 == 0:
                        logger.info(
                            f"[AUDIO-IN] received {_binary_count} binary msgs, "
                            f"{_binary_bytes} bytes total, "
                            f"buffer_size={len(self._buffer._buffer)} bytes"
                        )
                elif "text" in raw and raw["text"]:
                    msg = json.loads(raw["text"])
                    msg_type = msg.get("type", "")
                    if msg_type == "stop":
                        logger.info(f"LiveSession received stop: {self.meeting_id}")
                        await self._handle_stop()
                        break
                    elif msg_type == "ping":
                        await self._ws.send_json({"type": "pong"})
        except Exception as e:
            if self._running:
                logger.error(f"receive_loop error: {e}")
                await self._handle_stop()
        logger.debug("receive_loop stopped")

    async def _transcribe_loop(self) -> None:
        """后台任务：持续从 buffer 取 chunk → 转写 → 推送。"""
        logger.debug("transcribe_loop started")
        _chunk_count = 0
        _null_count = 0
        try:
            while self._running:
                chunk = self._buffer.process()
                if chunk is not None and self._transcriber:
                    _chunk_count += 1
                    if self._first_chunk:
                        logger.info(
                            f"[⑦ buffer.process] 首次产出音频块 | "
                            f"{len(chunk.data)} bytes, offset={chunk.offset_ms}ms, "
                            f"speech={chunk.is_speech}"
                        )
                        self._first_chunk = False
                    logger.info(
                        f"[CHUNK] #{_chunk_count}: {len(chunk.data)} bytes, "
                        f"offset={chunk.offset_ms}ms, speech={chunk.is_speech}, "
                        f"buffer_remaining={len(self._buffer._buffer)} bytes"
                    )
                    if self._first_transcribe_call:
                        logger.info(
                            f"[⑧ transcribe_chunk] 首次调用转写 | "
                            f"chunk_id={chunk.chunk_id}, bytes={len(chunk.data)}"
                        )
                        self._first_transcribe_call = False
                    segments_before = self._transcriber.segment_count
                    await self._transcriber.transcribe_chunk(chunk)
                    segments_after = self._transcriber.segment_count
                    logger.info(
                        f"[TRANSCRIBE] chunk #{_chunk_count}: "
                        f"segments {segments_before}→{segments_after} "
                        f"(+{segments_after - segments_before})"
                    )

                    if self._analyzer and segments_after > segments_before:
                        new_texts = self._transcriber.get_new_segment_texts(segments_before)
                        await self._analyzer.on_new_sentences(new_texts)
                        if self._first_analyzer_feed:
                            logger.info(
                                f"[⑭ analyzer.on_new_sentences] 首次喂入分析器 | "
                                f"sentences={len(new_texts)}, "
                                f"first='{new_texts[0][:50] if new_texts else ''}...'"
                            )
                            self._first_analyzer_feed = False
                else:
                    _null_count += 1
                    if _null_count % 200 == 0:  # ~10 seconds
                        total_frames = len(self._buffer._buffer) // self._buffer._frame_bytes
                        logger.debug(
                            f"[AUDIO-BUF] {_null_count} polls without chunk, "
                            f"buffer={len(self._buffer._buffer)} bytes, "
                            f"frames={total_frames}"
                        )
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
                    self._analyzer.last_analysis_time
                    if self._analyzer.last_analysis_time > 0
                    else self._started_at
                )
                elapsed = time.time() - ref_time
                if elapsed >= IncrementalAnalyzer.TRIGGER_TIME_SECONDS:
                    if self._first_force_analyze:
                        logger.info(
                            f"[⑮ analyzer.force_analyze] 首次触发LLM分析 | "
                            f"elapsed={elapsed:.1f}s"
                        )
                        self._first_force_analyze = False
                    await self._analyzer.force_analyze()
        except Exception as e:
            if self._running:
                logger.error(f"analyze_timer_loop error: {e}")
        logger.debug("analyze_timer_loop stopped")

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
        if self._first_push:
            logger.info(
                f"[⑬ _on_transcript_sentence] 首次推送转写结果到前端 | "
                f"speaker={segment.speaker}, text='{segment.text[:50]}...', "
                f"start={segment.start}s"
            )
            self._first_push = False
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
