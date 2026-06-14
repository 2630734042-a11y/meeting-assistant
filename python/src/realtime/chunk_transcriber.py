"""
ChunkTranscriber — 对音频块执行转写并逐句推送

每个 chunk 独立通过 WhisperX 转写，时间戳转换为全局偏移，
结果以 TranscriptSegment 列表形式返回。
"""

from __future__ import annotations

from typing import Callable, Awaitable

from loguru import logger

from ..agents.transcription_agent import TranscriptionAgent, TranscriptionConfig
from ..models.schemas import TranscriptSegment, TranscriptResult
from .audio_buffer import AudioChunk


OnSentenceCallback = Callable[[TranscriptSegment], Awaitable[None]]


class ChunkTranscriber:
    """
    分块转写器。

    职责:
    1. 接收 AudioChunk → 调用 WhisperX 转写
    2. 将 chunk 内时间戳转为全局绝对时间戳
    3. 逐句通过回调推送给调用方（通常是 WebSocket）
    4. 累积 transcript_text 供增量分析使用
    """

    def __init__(
        self,
        config: TranscriptionConfig | None = None,
        on_sentence: OnSentenceCallback | None = None,
    ):
        self._agent = TranscriptionAgent(config)
        self._on_sentence = on_sentence
        self._accumulated_segments: list[TranscriptSegment] = []
        self._accumulated_text: str = ""
        self._chunk_count = 0

    @property
    def accumulated_text(self) -> str:
        """获取累积的纯文本全文（供 IncrementalAnalyzer 使用）。"""
        return self._accumulated_text

    @property
    def segment_count(self) -> int:
        """已转写的句子总数。"""
        return len(self._accumulated_segments)

    async def transcribe_chunk(self, chunk: AudioChunk) -> list[TranscriptSegment]:
        """
        转写一个音频块。

        Args:
            chunk: 音频块（含数据和全局时间偏移）

        Returns:
            转写片段列表（时间戳已转为全局绝对时间）
        """
        self._chunk_count += 1
        logger.debug(
            f"ChunkTranscriber: chunk #{chunk.chunk_id} "
            f"({len(chunk.data)} bytes, offset={chunk.offset_ms}ms)"
        )

        try:
            result = await self._agent.transcribe_bytes(chunk.data)
        except Exception as e:
            logger.error(f"ChunkTranscriber error on chunk #{chunk.chunk_id}: {e}")
            return []

        # 时间戳转换: chunk 内相对时间 → 全局绝对时间
        offset_seconds = chunk.offset_ms / 1000.0
        global_segments: list[TranscriptSegment] = []

        for seg in result.segments:
            global_seg = TranscriptSegment(
                speaker=seg.speaker,
                text=seg.text,
                start=round(seg.start + offset_seconds, 2),
                end=round(seg.end + offset_seconds, 2),
                confidence=seg.confidence,
            )
            global_segments.append(global_seg)

            # 累积
            self._accumulated_segments.append(global_seg)
            if self._accumulated_text:
                self._accumulated_text += "\n"
            self._accumulated_text += (
                f"[{global_seg.start:.1f}s-{global_seg.end:.1f}s] "
                f"{global_seg.speaker}: {global_seg.text}"
            )

            # 逐句回调推送
            if self._on_sentence:
                try:
                    await self._on_sentence(global_seg)
                except Exception as e:
                    logger.error(f"on_sentence callback error: {e}")

        logger.info(
            f"ChunkTranscriber: chunk #{chunk.chunk_id} → "
            f"{len(global_segments)} segments, "
            f"total={len(self._accumulated_segments)}"
        )
        return global_segments

    def build_transcript_result(self, meeting_id: str) -> TranscriptResult:
        """构建累积的完整 TranscriptResult。"""
        full_text = " ".join(s.text for s in self._accumulated_segments)
        duration = (
            self._accumulated_segments[-1].end
            if self._accumulated_segments
            else 0.0
        )
        return TranscriptResult(
            meeting_id=meeting_id,
            segments=self._accumulated_segments,
            language=self._agent.config.language,
            duration_seconds=duration,
            full_text=full_text,
        )
